// Gesture icons come from the art pipeline (assets/icons/*.svg → build-art.mjs → assets/icons.js): hand, thumbs-up,
// thumbs-down, pointer, grab, swipe, head, camera-off, zoom (Lucide, ISC). The gesture UI draws them at 20 px.
import { icon as baseIcon } from "../assets/icons.js";
export const icon = (name, o = {}) => baseIcon(name, { size: 20, ...o });
