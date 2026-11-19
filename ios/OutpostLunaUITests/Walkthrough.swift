import XCTest

/// Drives the app by touch and the on-screen keyboard, like a cadet on an iPad (docs/IPAD.md "Simulator walkthrough").
/// Screenshots + accessibility dumps go to the runner's tmp/luna-shots; `ios/scripts/sim.sh test` copies them out.
final class Walkthrough: XCTestCase {
    let app = XCUIApplication()
    lazy var dir: URL = {
        let u = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("luna-shots")
        try? FileManager.default.createDirectory(at: u, withIntermediateDirectories: true)
        return u
    }()

    override func setUp() { continueAfterFailure = true }

    func shot(_ name: String) {
        let png = XCUIScreen.main.screenshot().pngRepresentation
        try? png.write(to: dir.appendingPathComponent("\(name).png"))
        try? app.debugDescription.write(to: dir.appendingPathComponent("\(name).txt"), atomically: true, encoding: .utf8)
        let a = XCTAttachment(data: png, uniformTypeIdentifier: "public.png"); a.name = name; a.lifetime = .keepAlways; add(a)
    }

    /// Tap the first hittable button whose label starts with one of `labels`. Returns the label tapped.
    @discardableResult
    func tap(_ labels: [String], timeout: TimeInterval = 8) -> String? {
        let end = Date().addingTimeInterval(timeout)
        var seen: (XCUIElement, String)?
        repeat {
            for l in labels {
                let q = app.buttons.matching(NSPredicate(format: "label BEGINSWITH[c] %@", l))
                for i in 0..<min(q.count, 6) {
                    let b = q.element(boundBy: i)
                    if b.exists && b.isEnabled && seen == nil && !b.frame.isEmpty { seen = (b, l) }
                    if b.exists && b.isHittable { b.tap(); return l }
                }
            }
            usleep(400_000)
        } while Date() < end
        // WebKit sometimes reports a visible control as not hittable: a real touch on its centre
        if let (b, l) = seen, app.frame.contains(CGPoint(x: b.frame.midX, y: b.frame.midY)) {
            b.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap(); return l
        }
        return nil
    }

    /// Type into the voice bar with the on-screen keyboard and send.
    func ask(_ text: String) {
        let f = app.textFields["Type to CAPCOM"]
        XCTAssertTrue(f.waitForExistence(timeout: 10), "the voice bar's text field")
        f.tap()
        f.typeText(text + "\n")
        sleep(3)
    }

    var webView: XCUIElement { app.webViews.firstMatch }

    func testFlightSchoolAndMission() throws {
        XCUIDevice.shared.orientation = .landscapeLeft
        let t0 = Date()
        app.launch()
        // 1. First launch: call sign by touch + the on-screen keyboard
        XCTAssertTrue(app.buttons["Start"].waitForExistence(timeout: 90), "home screen")
        NSLog("walkthrough: home after %.1f s", Date().timeIntervalSince(t0))
        let sign = app.textFields["Pick your call sign"]
        XCTAssertTrue(sign.exists, "call sign field")
        tap(["Comet"], timeout: 3)                      // a suggested call sign by touch, then make it ours
        sign.coordinate(withNormalizedOffset: CGVector(dx: 0.6, dy: 0.5)).tap()
        sign.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 24) + "Nova Fox")
        shot("01_call_sign")
        app.buttons["Start"].tap()
        sleep(4)
        shot("02_flight_school")
        targets("02_flight_school")

        // 2. The Moon by touch: drag to spin, pinch to zoom
        let w = webView
        w.coordinate(withNormalizedOffset: CGVector(dx: 0.6, dy: 0.5))
            .press(forDuration: 0.1, thenDragTo: w.coordinate(withNormalizedOffset: CGVector(dx: 0.35, dy: 0.5)))
        sleep(1)
        w.pinch(withScale: 1.6, velocity: 1.5)
        sleep(2)
        shot("03_moon_drag_pinch")
        w.pinch(withScale: 0.6, velocity: -1.5)
        sleep(1)

        // 3. A lesson by touch and typing
        XCTAssertNotNil(tap(["Start lesson"]), "Start lesson")
        sleep(3)
        shot("04_lesson_open")
        ask("Sea of Tranquility")                       // step 1: typed
        shot("05_step1_typed")
        XCTAssertNotNil(tap(["Next"]), "step 1 passed")
        sleep(2)
        XCTAssertNotNil(tap(["Yes"]), "step 2: tap an answer")   // step 2: tapped
        sleep(3)
        shot("06_step2_tapped")
        XCTAssertNotNil(tap(["Next"]), "step 2 passed")
        sleep(2)
        tap(["Yes, sometimes"], timeout: 4)             // step 3: guess, skip the video
        tap(["Skip"], timeout: 4)
        sleep(2)
        XCTAssertNotNil(tap(["Next"]), "step 3 passed")
        sleep(2)
        XCTAssertNotNil(tap(["Far side"]), "step 4: far side")
        sleep(3)
        tap(["Check this view"], timeout: 3)
        sleep(2)
        shot("07_step4_far_side")
        tap(["Next"], timeout: 4)
        sleep(2)
        ask("Shackleton")                               // step 5: typed
        sleep(2)
        shot("08_step5")
        tap(["Next", "Finish", "Done", "Continue"], timeout: 4)
        sleep(3)
        shot("09_lesson_done")

        // 4. Mission: a shift with the clock and the Now card
        let mission = app.switches["Mission"]
        if !(mission.exists && mission.isHittable) { tap(["Back to the map", "Back", "Close"], timeout: 3); sleep(2) }
        XCTAssertTrue(mission.waitForExistence(timeout: 5), "Mission tab")
        mission.tap()
        sleep(4)
        shot("10_mission")
        targets("10_mission")
        XCTAssertNotNil(tap(["Try a practice shift", "Start"]), "practice shift")
        sleep(4)
        shot("11_briefing")
        tap(["Take command", "Start", "Choose site"], timeout: 6)
        sleep(4)
        tap(["Take command", "Start"], timeout: 4)
        sleep(8)
        shot("12_shift")
        targets("12_shift")
        sleep(10)
        shot("13_shift_later")
        XCTAssertNotNil(tap(["Send the rover"], timeout: 10), "the Now card's job, by touch")
        sleep(6)
        shot("14_now_done")
    }

    /// Log every hittable control smaller than 44 x 44 pt (Apple's touch target) into <name>-targets.txt.
    func targets(_ name: String) {
        var small: [String] = []
        for q in [app.buttons, app.switches, app.textFields, app.links] {
            for e in q.allElementsBoundByIndex where e.exists && e.isHittable {
                let f = e.frame
                if f.width < 44 || f.height < 44 { small.append(String(format: "%.0fx%.0f  %@", f.width, f.height, e.label)) }
            }
        }
        try? small.joined(separator: "\n").write(to: dir.appendingPathComponent("\(name)-targets.txt"), atomically: true, encoding: .utf8)
        NSLog("walkthrough: %@ has %d controls under 44 pt", name, small.count)
    }
}
