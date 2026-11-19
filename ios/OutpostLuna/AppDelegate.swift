// Outpost Luna for iPad: a native shell around the same app the desktop runs (docs/IPAD.md).
//
//   UIApplication
//    └─ LunaViewController
//        ├─ splash "Warming up…" until GET /health answers
//        ├─ PythonHost: embedded CPython, ios/python/luna_ios.py -> backend + built frontend on 127.0.0.1:<free port>
//        └─ WKWebView -> http://127.0.0.1:<port>/   (luna_token cookie set first, like desktop/main/main.js)
import UIKit

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        true
    }

    func application(_ application: UIApplication, configurationForConnecting connectingSceneSession: UISceneSession,
                     options: UIScene.ConnectionOptions) -> UISceneConfiguration {
        let c = UISceneConfiguration(name: "Default", sessionRole: connectingSceneSession.role)
        c.delegateClass = SceneDelegate.self
        return c
    }
}

final class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let ws = scene as? UIWindowScene else { return }
        let w = UIWindow(windowScene: ws)
        w.rootViewController = LunaViewController()
        w.makeKeyAndVisible()
        window = w
    }

    func sceneWillEnterForeground(_ scene: UIScene) {
        (window?.rootViewController as? LunaViewController)?.didReturnToForeground()
    }
}
