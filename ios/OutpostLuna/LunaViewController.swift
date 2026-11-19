import UIKit
import WebKit
import os.log

/// One full-screen WKWebView. It shows the desktop's own splash (desktop/main/splash.html, bundled) while the embedded
/// backend starts, then the app itself from 127.0.0.1. docs/IPAD.md.
final class LunaViewController: UIViewController, WKNavigationDelegate, WKUIDelegate {
    private let log = Logger(subsystem: "ai.whissle.outpostluna", category: "shell")
    private var web: WKWebView!
    private let token = LunaViewController.newToken()
    private var port: Int = 0
    private let t0 = Date()
    private var appLoaded = false

    private static var support: URL {
        let u = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Outpost Luna", isDirectory: true)
        try? FileManager.default.createDirectory(at: u, withIntermediateDirectories: true)
        return u
    }

    /// 32 random bytes, URL-safe base64 (desktop/main/engine.js newToken).
    static func newToken() -> String {
        var b = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, b.count, &b)
        return Data(b).base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }

    override var prefersStatusBarHidden: Bool { true }
    override var prefersHomeIndicatorAutoHidden: Bool { true }

    override func loadView() {
        let c = WKWebViewConfiguration()
        c.allowsInlineMediaPlayback = true
        c.mediaTypesRequiringUserActionForPlayback = []
        c.websiteDataStore = .default()
        c.applicationNameForUserAgent = "OutpostLunaIPad/\(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") ?? "0")"
        // Touch: the page keeps its own pinch and drag (the Moon, the cabin); the page itself never zooms or bounces,
        // and a long press on a control is not a text callout.
        let touch = """
        (function(){
          var m=document.querySelector('meta[name=viewport]');
          if(m){m.setAttribute('content','width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover');}
          var s=document.createElement('style');
          s.textContent='html{-webkit-text-size-adjust:100%;-webkit-tap-highlight-color:transparent}'+
            'button,[role=button],a,canvas,.stage{-webkit-touch-callout:none;-webkit-user-select:none;user-select:none}'+
            // Apple's 44 pt touch target: the bar icons, chips and tabs use --control-sm (36 px on desktop)
            ':root{--control-sm:44px}.modes button{min-height:44px}.vs-grip{width:44px}';
          document.documentElement.appendChild(s);
        })();
        """
        c.userContentController.addUserScript(WKUserScript(source: touch, injectionTime: .atDocumentEnd, forMainFrameOnly: true))
        // No local ear on iPad yet (docs/IPAD.md): the page starts in "type, or the system's speech recognition"
        // (frontend/src/engine.js __lunaEngineBoot), never "Starting voice…".
        c.userContentController.addUserScript(WKUserScript(source: "window.__lunaEngineBoot={ear:'none'};",
                                                           injectionTime: .atDocumentStart, forMainFrameOnly: true))
        web = WKWebView(frame: .zero, configuration: c)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.isOpaque = false
        web.backgroundColor = UIColor(red: 0.02, green: 0.03, blue: 0.05, alpha: 1)   // the splash's --bg
        web.scrollView.bounces = false
        web.scrollView.contentInsetAdjustmentBehavior = .never
        web.allowsLinkPreview = false
        #if DEBUG
        if #available(iOS 16.4, *) { web.isInspectable = true }
        #endif
        view = web
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        if let u = Bundle.main.url(forResource: "splash", withExtension: "html"), let html = try? String(contentsOf: u, encoding: .utf8) {
            web.loadHTMLString(html, baseURL: nil)
        }
        startBackend()
    }

    // MARK: backend

    private func startBackend() {
        let portFile = FileManager.default.temporaryDirectory.appendingPathComponent("luna-port-\(getpid())")
        try? FileManager.default.removeItem(at: portFile)
        let env = [
            "LUNA_RESOURCES": Bundle.main.resourcePath ?? "",
            "LUNA_SUPPORT": Self.support.path,
            "LUNA_TOKEN": token,
            "LUNA_PORT_FILE": portFile.path,
            "LUNA_PORT": ProcessInfo.processInfo.environment["LUNA_PORT"] ?? "0",
            "TMPDIR": FileManager.default.temporaryDirectory.path,
        ]
        PythonHost.start(withEnvironment: env) { [weak self] code in
            self?.log.error("backend exited: \(code)")
            self?.fail()
        }
        waitForPort(portFile, tries: 0)
    }

    private func waitForPort(_ f: URL, tries: Int) {
        if let s = try? String(contentsOf: f, encoding: .utf8), let p = Int(s.trimmingCharacters(in: .whitespacesAndNewlines)), p > 0 {
            port = p
            waitForHealth(tries: 0)
            return
        }
        if tries > 1200 { fail(); return }          // 60 s
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { [weak self] in self?.waitForPort(f, tries: tries + 1) }
    }

    private var origin: String { "http://127.0.0.1:\(port)" }

    private func waitForHealth(tries: Int) {
        var r = URLRequest(url: URL(string: "\(origin)/api/health")!, timeoutInterval: 2)
        r.setValue(token, forHTTPHeaderField: "X-Luna-Token")
        URLSession.shared.dataTask(with: r) { [weak self] _, resp, _ in
            DispatchQueue.main.async {
                guard let self else { return }
                if (resp as? HTTPURLResponse)?.statusCode == 200 { self.openApp(); return }
                if tries > 600 { self.fail(); return }  // ~60 s after the port is known
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { self.waitForHealth(tries: tries + 1) }
            }
        }.resume()
    }

    private func openApp() {
        let ms = Int(Date().timeIntervalSince(t0) * 1000)
        log.notice("luna: backend ready in \(ms) ms on port \(self.port)")
        NSLog("luna: backend ready in %d ms on port %d", ms, port)
        // The page gets the token as a cookie on its own origin, HttpOnly + SameSite=Strict (docs/SECURITY.md).
        let props: [HTTPCookiePropertyKey: Any] = [
            .name: "luna_token", .value: token, .domain: "127.0.0.1", .path: "/",
            HTTPCookiePropertyKey("HttpOnly"): "TRUE", .sameSitePolicy: HTTPCookieStringPolicy.sameSiteStrict,
        ]
        guard let cookie = HTTPCookie(properties: props) else { fail(); return }
        web.configuration.websiteDataStore.httpCookieStore.setCookie(cookie) { [weak self] in
            guard let self else { return }
            self.appLoaded = true
            self.web.load(URLRequest(url: URL(string: "\(self.origin)/")!))
        }
    }

    private func fail() {
        let js = "window.setStatus && window.setStatus('Outpost Luna didn\\u2019t start. Close it and open it again.')"
        if appLoaded {
            if let u = Bundle.main.url(forResource: "splash", withExtension: "html"), let html = try? String(contentsOf: u, encoding: .utf8) {
                appLoaded = false
                web.loadHTMLString(html, baseURL: nil)
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in self?.web.evaluateJavaScript(js) }
            }
        } else {
            web.evaluateJavaScript(js)
        }
    }

    /// Back from the background: iOS may have suspended the backend thread; it resumes with the app. If the loopback
    /// socket was reclaimed meanwhile the page's own offline banner keeps retrying; reload once it answers again.
    func didReturnToForeground() {
        guard port > 0 else { return }
        var r = URLRequest(url: URL(string: "\(origin)/api/health")!, timeoutInterval: 2)
        r.setValue(token, forHTTPHeaderField: "X-Luna-Token")
        URLSession.shared.dataTask(with: r) { [weak self] _, resp, _ in
            if (resp as? HTTPURLResponse)?.statusCode != 200 {
                self?.log.error("luna: backend not answering after foreground")
            }
        }.resume()
    }

    // MARK: navigation: the web view stays on its own origin

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "about" || url.absoluteString.hasPrefix(origin + "/") || url.absoluteString == origin {
            decisionHandler(.allow); return
        }
        if action.targetFrame?.isMainFrame == false, url.host == "127.0.0.1" { decisionHandler(.allow); return }
        decisionHandler(.cancel)
        if Self.mayOpenOutside(url) { UIApplication.shared.open(url) }
    }

    /// Links that may leave the app (to Safari): the project's own pages and NASA, https only.
    static func mayOpenOutside(_ url: URL) -> Bool {
        guard url.scheme == "https", let h = url.host?.lowercased() else { return false }
        if h == "whissleai.github.io" { return url.path.hasPrefix("/Outpost-Luna") }
        if h == "github.com" { return url.path.hasPrefix("/WhissleAI/Outpost-Luna") }
        return h == "nasa.gov" || h.hasSuffix(".nasa.gov")
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let u = navigationAction.request.url, Self.mayOpenOutside(u) { UIApplication.shared.open(u) }
        return nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard appLoaded else { return }
        let ms = Int(Date().timeIntervalSince(t0) * 1000)
        let probe = "JSON.stringify({sr: !!(window.SpeechRecognition||window.webkitSpeechRecognition), " +
            "tts: !!window.speechSynthesis, voices: window.speechSynthesis ? speechSynthesis.getVoices().length : 0, " +
            "worklet: !!window.AudioWorkletNode, gum: !!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia), " +
            "w: innerWidth, h: innerHeight, dpr: devicePixelRatio})"
        webView.evaluateJavaScript(probe) { r, _ in
            NSLog("luna: page loaded at %d ms %@", ms, (r as? String) ?? "?")
        }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        log.error("luna: web content process ended; reloading")
        if appLoaded { webView.reload() }
    }

    // MARK: permissions and dialogs

    /// The microphone for the page's own origin only. The camera (hand gestures) is off in the iPad v1.
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                 initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
                 decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        let ours = origin.host == "127.0.0.1" && origin.port == port
        decisionHandler(ours && type == .microphone ? .grant : .deny)
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
        present(a, animated: true)
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(false) })
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(true) })
        present(a, animated: true)
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let a = UIAlertController(title: nil, message: prompt, preferredStyle: .alert)
        a.addTextField { $0.text = defaultText }
        a.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(nil) })
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(a.textFields?.first?.text) })
        present(a, animated: true)
    }
}
