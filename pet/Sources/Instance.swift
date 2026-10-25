import Foundation
import Darwin

/// 单实例：避免开机自启 + 手动双击时出现两只兔子
enum SingleInstance {
    private static var lockDescriptor: Int32 = -1

    static func claim() -> Bool {
        let directory = AppStorage.directory
        try? FileManager.default.createDirectory(atPath: directory, withIntermediateDirectories: true)
        let path = directory + "/instance.lock"
        let descriptor = open(path, O_CREAT | O_RDWR, 0o644)
        guard descriptor >= 0 else { return true }
        if flock(descriptor, LOCK_EX | LOCK_NB) == 0 {
            lockDescriptor = descriptor
            return true
        }
        close(descriptor)
        return false
    }

    /// 已有实例在运行时，请它把气泡亮出来
    static func requestShow() {
        DistributedNotificationCenter.default().post(name: Notification.Name("top.rabbitj.balancepet.show"),
                                                     object: nil)
    }
}
