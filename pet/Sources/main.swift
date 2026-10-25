import Cocoa

let arguments = CommandLine.arguments

if let index = arguments.firstIndex(of: "--render"), index + 1 < arguments.count {
    _ = NSApplication.shared
    NSApp.setActivationPolicy(.prohibited)
    renderSnapshots(to: arguments[index + 1])
    exit(0)
}

if arguments.contains("--enable-login") {
    print(LoginItem.enable() ?? "ok")
    exit(0)
}

if arguments.contains("--disable-login") {
    LoginItem.disable()
    print("ok")
    exit(0)
}

if arguments.contains("--stats") {
    _ = NSApplication.shared
    NSApp.setActivationPolicy(.prohibited)
    runStatsCLI()
    exit(0)
}

if !SingleInstance.claim() {
    SingleInstance.requestShow()
    exit(0)
}

let appDelegate = AppDelegate()
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
app.delegate = appDelegate
app.run()
