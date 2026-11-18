// Model step of scripts/nasa_views_build.py (the optional `nasa_views` asset): one GLB out of one or more source GLBs or
// one OBJ (+ .mtl + texture; read here, no converter), cleaned and made small for the app:
//   merge parts -> centre (base on y=0 for hardware, the middle for rocks) -> dedup / weld / simplify -> textures
//   resized to <= 1024 px WebP -> prune -> EXT_meshopt_compression.  Prints {"bytes", "size": [x, y, z]} as JSON.
//
//   node scripts/nasa_views_glb.mjs <node_modules dir> <out.glb> <json options> <in1> [in2 ...]
//   options: {"pivot": "below" | "center", "ratio": 0..1 (simplify; 1 = keep), "error": 0.001, "scale": 1, "tex": 1024}
//
// The npm packages are installed by the builder into its raw cache (never into the repo); their folder comes as argv[2].
import { createRequire } from "module";
import { pathToFileURL } from "url";
import fs from "fs";
import path from "path";

const [nm, out, optJson, ...inputs] = process.argv.slice(2);
if (!nm || !out || !inputs.length) { console.error("usage: nasa_views_glb.mjs <node_modules> <out.glb> <opts> <in...>"); process.exit(2); }
const opt = { pivot: "below", ratio: 1, error: 0.001, scale: 1, tex: 1024, ...JSON.parse(optJson || "{}") };
const req = createRequire(path.join(path.resolve(nm), "x.js"));
const imp = (id) => import(pathToFileURL(req.resolve(id)).href);

const coreMod = await imp("@gltf-transform/core");
const { NodeIO } = coreMod;
const { ALL_EXTENSIONS } = await imp("@gltf-transform/extensions");
const F = await imp("@gltf-transform/functions");
const draco3d = (await imp("draco3dgltf")).default;
const { MeshoptEncoder, MeshoptDecoder, MeshoptSimplifier } = await imp("meshoptimizer");
const sharp = (await imp("sharp")).default;

await MeshoptEncoder.ready; await MeshoptDecoder.ready; await MeshoptSimplifier.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
  "draco3d.decoder": await draco3d.createDecoderModule(), "meshopt.decoder": MeshoptDecoder, "meshopt.encoder": MeshoptEncoder,
});

/** A photogrammetry OBJ (Astromaterials 3D: v, vt, triangles, one textured material) -> a Document,
 *  with smooth (area-weighted) vertex normals computed here so the rock is lit right. */
function readObj(p) {
  const { Document } = coreMod;
  const text = fs.readFileSync(p, "utf8");
  const v = [], vt = [], pos = [], uv = [], key = new Map(), idx = [];
  let mtl = null;
  for (const line of text.split(/\r?\n/)) {
    if (line.startsWith("v ")) { const a = line.trim().split(/\s+/); v.push([+a[1], +a[2], +a[3]]); }
    else if (line.startsWith("vt ")) { const a = line.trim().split(/\s+/); vt.push([+a[1], 1 - +a[2]]); }
    else if (line.startsWith("mtllib ")) mtl = line.slice(7).trim();
    else if (line.startsWith("f ")) {
      const c = line.trim().split(/\s+/).slice(1).map((t) => {
        if (!key.has(t)) {
          const [a, b] = t.split("/"); const P = v[(+a > 0 ? +a : v.length + +a + 1) - 1], T = b ? vt[(+b > 0 ? +b : vt.length + +b + 1) - 1] : [0, 0];
          key.set(t, pos.length / 3); pos.push(...P); uv.push(...T);
        }
        return key.get(t);
      });
      for (let i = 1; i + 1 < c.length; i++) idx.push(c[0], c[i], c[i + 1]);
    }
  }
  const nrm = new Float32Array(pos.length);
  for (let i = 0; i < idx.length; i += 3) {
    const [a, b, c] = [idx[i] * 3, idx[i + 1] * 3, idx[i + 2] * 3];
    const e1 = [pos[b] - pos[a], pos[b + 1] - pos[a + 1], pos[b + 2] - pos[a + 2]], e2 = [pos[c] - pos[a], pos[c + 1] - pos[a + 1], pos[c + 2] - pos[a + 2]];
    const n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
    for (const k of [a, b, c]) { nrm[k] += n[0]; nrm[k + 1] += n[1]; nrm[k + 2] += n[2]; }
  }
  for (let i = 0; i < nrm.length; i += 3) { const l = Math.hypot(nrm[i], nrm[i + 1], nrm[i + 2]) || 1; nrm[i] /= l; nrm[i + 1] /= l; nrm[i + 2] /= l; }
  const doc = new Document(), buf = doc.createBuffer();
  const acc = (type, arr) => doc.createAccessor().setType(type).setArray(arr).setBuffer(buf);
  const mat = doc.createMaterial("rock").setRoughnessFactor(0.95).setMetallicFactor(0);
  const tex = mtl && (fs.readFileSync(path.join(path.dirname(p), mtl), "utf8").match(/map_Kd\s+(.+)/) || [])[1];
  if (tex) {
    const f = path.join(path.dirname(p), tex.trim());
    mat.setBaseColorTexture(doc.createTexture("albedo").setImage(new Uint8Array(fs.readFileSync(f))).setMimeType("image/jpeg").setURI(path.basename(f)));
  }
  const prim = doc.createPrimitive().setMaterial(mat)
    .setAttribute("POSITION", acc("VEC3", new Float32Array(pos))).setAttribute("NORMAL", acc("VEC3", nrm))
    .setAttribute("TEXCOORD_0", acc("VEC2", new Float32Array(uv)))
    .setIndices(acc("SCALAR", pos.length / 3 > 65535 ? new Uint32Array(idx) : new Uint16Array(idx)));
  const mesh = doc.createMesh(path.basename(p, ".obj")).addPrimitive(prim);
  doc.createScene("rock").addChild(doc.createNode("rock").setMesh(mesh));
  return doc;
}

async function load(p) { return /\.obj$/i.test(p) ? readObj(p) : io.read(p); }

const doc = await load(inputs[0]);
for (const more of inputs.slice(1)) F.mergeDocuments(doc, await load(more));   // HDU: part 1 + part 2
// one scene holding every root node (merged parts arrive as extra scenes)
const root = doc.getRoot(), scenes = root.listScenes(), scene = scenes[0];
for (const s of scenes.slice(1)) { for (const n of s.listChildren()) scene.addChild(n); s.dispose(); }
root.setDefaultScene(scene);
if (opt.scale !== 1) for (const n of scene.listChildren()) n.setScale(n.getScale().map((v) => v * opt.scale));

await doc.transform(
  F.unpartition(), F.dedup(), F.flatten(), F.join(), F.weld(),
  ...(opt.ratio < 1 ? [F.simplify({ simplifier: MeshoptSimplifier, ratio: opt.ratio, error: opt.error })] : []),
  F.center({ pivot: opt.pivot }),
  F.textureCompress({ encoder: sharp, targetFormat: "webp", resize: [opt.tex, opt.tex], quality: 82 }),
  F.prune(), F.dedup(),
  F.reorder({ encoder: MeshoptEncoder }),
  F.quantize(),
);
// strip any draco left from the source, then meshopt
root.listExtensionsUsed().filter((e) => e.extensionName === "KHR_draco_mesh_compression").forEach((e) => e.dispose());
const meshopt = doc.createExtension((await imp("@gltf-transform/extensions")).EXTMeshoptCompression).setRequired(true)
  .setEncoderOptions({ method: "filter" });
void meshopt;
fs.mkdirSync(path.dirname(out), { recursive: true });
await io.write(out, doc);
const b = F.getBounds(scene);
const size = b.max.map((v, i) => +(v - b.min[i]).toFixed(4));
console.log(JSON.stringify({ bytes: fs.statSync(out).size, size }));
