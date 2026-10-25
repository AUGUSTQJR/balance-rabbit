using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using Microsoft.Win32;

namespace BalanceRabbit.Setup
{
    /// <summary>安装 / 卸载逻辑（当前用户安装，无需管理员权限；目录不可写时自动换位置）。</summary>
    internal static class Installer
    {
        public const string Version = "1.2.0";
        public const string ProductName = "余额兔";

        private const string UninstallKey =
            @"Software\Microsoft\Windows\CurrentVersion\Uninstall\BalanceRabbit";

        private const string RunKey =
            @"Software\Microsoft\Windows\CurrentVersion\Run";

        private const string RunValue = "BalanceRabbit";

        private static string resolvedDir;

        public static string LogPath
        {
            get { return Path.Combine(Path.GetTempPath(), "BalanceRabbit-install.log"); }
        }

        public static string DefaultInstallDir
        {
            get
            {
                return Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Programs", "BalanceRabbit");
            }
        }

        /// <summary>本次安装实际使用的目录（未选择时为默认目录）。</summary>
        public static string InstallDir
        {
            get
            {
                if (!string.IsNullOrEmpty(resolvedDir)) return resolvedDir;
                string stored = ReadInstallLocation();
                return string.IsNullOrEmpty(stored) ? DefaultInstallDir : stored;
            }
        }

        public static string AppExePath
        {
            get { return Path.Combine(InstallDir, "BalanceRabbit.exe"); }
        }

        public static string UninstallExePath
        {
            get { return Path.Combine(InstallDir, "uninstall.exe"); }
        }

        public static string ReadmePath
        {
            get { return Path.Combine(InstallDir, "使用说明.txt"); }
        }

        public static string SelfPath
        {
            get
            {
                try
                {
                    return Process.GetCurrentProcess().MainModule.FileName;
                }
                catch
                {
                    return Assembly.GetExecutingAssembly().Location;
                }
            }
        }

        private static string DesktopDir
        {
            get { return Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory); }
        }

        private static string StartMenuDir
        {
            get
            {
                return Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.Programs),
                    ProductName);
            }
        }

        // ---------------- 安装 ----------------

        public static void Install(bool createStartup, string preferredDirectory,
            Action<string> progress)
        {
            ResetLog();
            Report(progress, "正在准备安装目录…");
            Exception lastError = null;
            var attempted = new List<string>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (string candidate in CandidateDirectories(preferredDirectory))
            {
                if (!seen.Add(candidate)) continue;
                attempted.Add(candidate);
                try
                {
                    Log("尝试安装目录：" + candidate);
                    KillRunningIn(candidate);
                    PrepareDirectory(candidate);
                    ExtractResource("Setup.payload.app.exe", Path.Combine(candidate, "BalanceRabbit.exe"));
                    resolvedDir = candidate;
                    Log("选用安装目录：" + candidate);
                    break;
                }
                catch (Exception ex)
                {
                    lastError = ex;
                    Log("  失败：" + Describe(ex));
                }
            }

            if (string.IsNullOrEmpty(resolvedDir))
            {
                throw new IOException(
                    "安装目录不可写，已尝试：\n" + string.Join("\n", attempted.ToArray()) +
                    "\n\n最后一次错误：" + Describe(lastError) +
                    "\n\n安装日志：" + LogPath, lastError);
            }

            Report(progress, "安装位置：" + resolvedDir);

            try
            {
                ExtractResource("Setup.payload.app.config", AppExePath + ".config");
            }
            catch (Exception ex)
            {
                Log("配置文件写入失败（可忽略）：" + Describe(ex));
            }

            Report(progress, "正在写入使用说明…");
            try
            {
                ExtractResource("Setup.readme.txt", ReadmePath);
            }
            catch (Exception ex)
            {
                Log("使用说明写入失败：" + Describe(ex));
            }

            Report(progress, "正在准备卸载程序…");
            if (!string.Equals(SelfPath, UninstallExePath, StringComparison.OrdinalIgnoreCase))
            {
                File.Copy(SelfPath, UninstallExePath, true);
            }

            Report(progress, "正在创建快捷方式…");
            CreateShortcuts();

            Report(progress, "正在写入卸载信息…");
            WriteUninstallRegistry();

            Report(progress, "正在设置开机启动…");
            SetStartup(createStartup);

            WriteInstallMarker();

            Log("安装完成：" + resolvedDir);
            Report(progress, "安装完成");
        }

        /// <summary>把用户选的父文件夹转换成安装目录（自动加 BalanceRabbit 子文件夹）。</summary>
        public static string ResolveTargetFromSelection(string selectedFolder)
        {
            if (string.IsNullOrEmpty(selectedFolder)) return DefaultInstallDir;
            string full;
            try
            {
                full = Path.GetFullPath(selectedFolder).TrimEnd('\\');
            }
            catch
            {
                return DefaultInstallDir;
            }
            string leaf = Path.GetFileName(full);
            if (string.Equals(leaf, "BalanceRabbit", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(leaf, "BalanceRabbitApp", StringComparison.OrdinalIgnoreCase))
            {
                return full;
            }
            return Path.Combine(full, "BalanceRabbit");
        }

        private static IEnumerable<string> CandidateDirectories(string preferredDirectory)
        {
            var list = new List<string>();
            if (!string.IsNullOrEmpty(preferredDirectory))
            {
                list.Add(preferredDirectory);
            }

            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string roaming = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);

            list.Add(Path.Combine(local, "Programs", "BalanceRabbit"));
            list.Add(Path.Combine(local, "BalanceRabbit"));
            list.Add(Path.Combine(roaming, "BalanceRabbitApp"));
            list.Add(Path.Combine(profile, "BalanceRabbitApp"));

            // 安全软件常拦用户目录；这几个位置多数环境仍可写
            try
            {
                string selfDir = Path.GetDirectoryName(SelfPath);
                if (!string.IsNullOrEmpty(selfDir))
                {
                    list.Add(Path.Combine(selfDir, "BalanceRabbit"));
                }
            }
            catch
            {
                // 忽略
            }
            list.Add(Path.Combine(Path.GetTempPath(), "BalanceRabbit"));
            list.Add(Path.Combine(Environment.GetFolderPath(
                Environment.SpecialFolder.CommonApplicationData), "BalanceRabbit"));
            return list;
        }

        /// <summary>留给应用启动时判断“这是新装的”，用来确认当前 API Key 是不是本机使用者本人的。</summary>
        private static void WriteInstallMarker()
        {
            try
            {
                string dir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "BalanceRabbit");
                Directory.CreateDirectory(dir);
                File.WriteAllText(Path.Combine(dir, "just-installed.txt"),
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"), Encoding.UTF8);
            }
            catch (Exception ex)
            {
                Log("写入首次启动标记失败（不影响安装）：" + Describe(ex));
            }
        }

        private static void PrepareDirectory(string directory)
        {
            Directory.CreateDirectory(directory);
            string probe = Path.Combine(directory, ".write-test-" + Guid.NewGuid().ToString("N"));
            File.WriteAllText(probe, "ok", Encoding.UTF8);
            File.Delete(probe);
        }

        public static void LaunchApp()
        {
            try
            {
                var info = new ProcessStartInfo(AppExePath);
                info.WorkingDirectory = InstallDir;
                info.UseShellExecute = true;
                Process.Start(info);
            }
            catch
            {
                // 启动失败时用户可手动双击快捷方式
            }
        }

        private static void ExtractResource(string name, string destination)
        {
            using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
            {
                if (stream == null) throw new InvalidOperationException("安装包缺少资源：" + name);
                Exception last = null;
                for (int attempt = 0; attempt < 12; attempt++)
                {
                    try
                    {
                        string temp = destination + ".tmp";
                        using (var file = new FileStream(temp, FileMode.Create, FileAccess.Write,
                                   FileShare.None))
                        {
                            stream.Position = 0;
                            stream.CopyTo(file);
                        }
                        if (File.Exists(destination)) File.Delete(destination);
                        File.Move(temp, destination);
                        return;
                    }
                    catch (Exception ex)
                    {
                        last = ex;
                        Log("    写入重试 " + (attempt + 1) + "/12：" + Describe(ex));
                        Thread.Sleep(500);
                    }
                }
                throw new IOException("写入文件失败：" + destination, last);
            }
        }

        private static void CreateShortcuts()
        {
            string desktop = Path.Combine(DesktopDir, ProductName + ".lnk");
            string startApp = Path.Combine(StartMenuDir, ProductName + ".lnk");
            string startUninstall = Path.Combine(StartMenuDir, "卸载" + ProductName + ".lnk");
            try
            {
                Directory.CreateDirectory(StartMenuDir);
            }
            catch
            {
                // 忽略
            }

            CreateShortcut(desktop, AppExePath, "", InstallDir, AppExePath, "余额兔 · 桌面余额宠物");
            CreateShortcut(startApp, AppExePath, "", InstallDir, AppExePath, "余额兔 · 桌面余额宠物");
            CreateShortcut(startUninstall, UninstallExePath, "/uninstall",
                Path.GetTempPath(), AppExePath, "卸载余额兔");
        }

        private static void CreateShortcut(string path, string target, string arguments,
            string workingDirectory, string iconFile, string description)
        {
            try
            {
                Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType == null) return;
                object shell = Activator.CreateInstance(shellType);
                object shortcut = shellType.InvokeMember("CreateShortcut",
                    BindingFlags.InvokeMethod, null, shell, new object[] { path });
                Type shortcutType = shortcut.GetType();
                shortcutType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut,
                    new object[] { target });
                shortcutType.InvokeMember("Arguments", BindingFlags.SetProperty, null, shortcut,
                    new object[] { arguments });
                shortcutType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut,
                    new object[] { workingDirectory });
                shortcutType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut,
                    new object[] { iconFile + ",0" });
                shortcutType.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut,
                    new object[] { description });
                shortcutType.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);

                if (shortcut != null && Marshal.IsComObject(shortcut)) Marshal.ReleaseComObject(shortcut);
                if (shell != null && Marshal.IsComObject(shell)) Marshal.ReleaseComObject(shell);
            }
            catch (Exception ex)
            {
                Log("快捷方式失败（" + path + "）：" + Describe(ex));
            }
        }

        private static void WriteUninstallRegistry()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(UninstallKey))
                {
                    if (key == null) return;
                    key.SetValue("DisplayName", ProductName + "（Windows 桌面余额宠物）");
                    key.SetValue("DisplayVersion", Version);
                    key.SetValue("Publisher", "余额兔 · rabbitj.top");
                    key.SetValue("DisplayIcon", AppExePath + ",0");
                    key.SetValue("InstallLocation", InstallDir);
                    key.SetValue("InstallDate", DateTime.Now.ToString("yyyyMMdd"));
                    key.SetValue("URLInfoAbout", "https://www.rabbitj.top");
                    key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                    key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                    key.SetValue("UninstallString", "\"" + UninstallExePath + "\" /uninstall");
                    key.SetValue("QuietUninstallString", "\"" + UninstallExePath + "\" /uninstall /S");
                    key.SetValue("EstimatedSize", EstimateSizeKb(), RegistryValueKind.DWord);
                }
            }
            catch (Exception ex)
            {
                Log("卸载注册表写入失败：" + Describe(ex));
            }
        }

        private static int EstimateSizeKb()
        {
            try
            {
                long total = 0;
                foreach (string file in Directory.GetFiles(InstallDir))
                {
                    total += new FileInfo(file).Length;
                }
                return (int)Math.Max(1, total / 1024);
            }
            catch
            {
                return 1024;
            }
        }

        private static void SetStartup(bool enabled)
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(RunKey))
                {
                    if (key == null) return;
                    if (enabled) key.SetValue(RunValue, "\"" + AppExePath + "\"");
                    else key.DeleteValue(RunValue, false);
                }
            }
            catch (Exception ex)
            {
                Log("开机自启设置失败：" + Describe(ex));
            }
        }

        private static void DeleteStartup()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RunKey, true))
                {
                    if (key != null) key.DeleteValue(RunValue, false);
                }
            }
            catch (Exception ex)
            {
                Log("删除开机自启失败：" + Describe(ex));
            }
        }

        public static bool IsStartupEnabled()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RunKey, false))
                {
                    if (key == null) return false;
                    var value = key.GetValue(RunValue) as string;
                    return !string.IsNullOrEmpty(value);
                }
            }
            catch
            {
                return false;
            }
        }

        private static string ReadInstallLocation()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(UninstallKey, false))
                {
                    if (key == null) return null;
                    var value = key.GetValue("InstallLocation") as string;
                    return string.IsNullOrEmpty(value) ? null : value;
                }
            }
            catch
            {
                return null;
            }
        }

        // ---------------- 卸载 ----------------

        /// <summary>卸载第一步：关闭程序、删快捷方式与注册表。调用方提示用户后再调 FinishRemoval。</summary>
        public static void Uninstall(bool silent, Action<string> progress)
        {
            ResetLog();
            string directory = ReadInstallLocation();
            if (string.IsNullOrEmpty(directory))
            {
                directory = Path.GetDirectoryName(SelfPath) ?? DefaultInstallDir;
            }
            resolvedDir = directory;
            Report(progress, "正在关闭余额兔…");
            KillRunningIn(directory);

            Report(progress, "正在删除快捷方式…");
            DeleteShortcuts();

            Report(progress, "正在清理注册表…");
            DeleteStartup();
            try
            {
                Registry.CurrentUser.DeleteSubKeyTree(UninstallKey, false);
            }
            catch (Exception ex)
            {
                Log("删除卸载注册表失败：" + Describe(ex));
            }

            try
            {
                string marker = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "BalanceRabbit", "just-installed.txt");
                if (File.Exists(marker)) File.Delete(marker);
            }
            catch
            {
                // 忽略
            }
        }

        /// <summary>卸载第二步：延迟删除程序目录（先把正在运行的卸载程序自己留下，2 秒后整体删除）。</summary>
        public static void FinishRemoval()
        {
            ScheduleSelfDelete();
        }

        private static void DeleteShortcuts()
        {
            string[] files =
            {
                Path.Combine(DesktopDir, ProductName + ".lnk"),
                Path.Combine(StartMenuDir, ProductName + ".lnk"),
                Path.Combine(StartMenuDir, "卸载" + ProductName + ".lnk")
            };
            foreach (string file in files)
            {
                try
                {
                    if (File.Exists(file)) File.Delete(file);
                }
                catch (Exception ex)
                {
                    Log("删除快捷方式失败（" + file + "）：" + Describe(ex));
                }
            }
            try
            {
                if (Directory.Exists(StartMenuDir) && Directory.GetFileSystemEntries(StartMenuDir).Length == 0)
                {
                    Directory.Delete(StartMenuDir);
                }
            }
            catch
            {
                // 忽略
            }
        }

        private static void ScheduleSelfDelete()
        {
            string directory = Path.GetDirectoryName(SelfPath) ?? InstallDir;
            directory = Path.GetFullPath(directory).TrimEnd('\\');
            if (!IsSafeInstallDirectory(directory))
            {
                throw new InvalidOperationException("安装目录异常，已取消删除：" + directory);
            }

            string temp = Path.GetTempPath();
            string script = Path.Combine(temp, "BalanceRabbit-uninstall-" +
                Guid.NewGuid().ToString("N") + ".bat");
            string quoted = "\"" + directory + "\"";
            string content =
                "@echo off\r\n" +
                "cd /d \"" + temp + "\"\r\n" +
                "for /l %%i in (1,1,30) do (\r\n" +
                "  rmdir /s /q " + quoted + " 2>nul\r\n" +
                "  if not exist " + quoted + " goto done\r\n" +
                "  ping -n 2 127.0.0.1 >nul\r\n" +
                ")\r\n" +
                ":done\r\n" +
                "del \"%~f0\" >nul\r\n";
            File.WriteAllText(script, content, Encoding.Default);

            var info = new ProcessStartInfo("cmd.exe", "/c \"" + script + "\"");
            info.WorkingDirectory = temp;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.WindowStyle = ProcessWindowStyle.Hidden;
            Process.Start(info);
        }

        private static bool IsSafeInstallDirectory(string directory)
        {
            string name = Path.GetFileName(directory);
            if (!string.Equals(name, "BalanceRabbit", StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(name, "BalanceRabbitApp", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            string root = Path.GetPathRoot(directory);
            if (string.IsNullOrEmpty(root)) return false;
            if (string.Equals(directory.TrimEnd(Path.DirectorySeparatorChar),
                root.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            // 只有确实包含本程序的目录才允许整体删除，避免误删用户自建的同名目录
            if (!File.Exists(Path.Combine(directory, "uninstall.exe")) &&
                !File.Exists(Path.Combine(directory, "BalanceRabbit.exe")))
            {
                return false;
            }
            return true;
        }

        public static void KillRunningIn(string directory)
        {
            string target;
            try
            {
                target = Path.GetFullPath(Path.Combine(directory, "BalanceRabbit.exe"));
            }
            catch
            {
                return;
            }

            try
            {
                foreach (Process process in Process.GetProcessesByName("BalanceRabbit"))
                {
                    try
                    {
                        string path = process.MainModule.FileName;
                        if (!string.Equals(Path.GetFullPath(path), target,
                            StringComparison.OrdinalIgnoreCase)) continue;
                        process.Kill();
                        process.WaitForExit(3000);
                    }
                    catch
                    {
                        // 忽略
                    }
                }
            }
            catch
            {
                // 忽略
            }
        }

        /// <summary>保留旧入口：只结束默认目录里的进程。</summary>
        public static void KillRunning()
        {
            KillRunningIn(DefaultInstallDir);
        }

        public static bool IsInstalled
        {
            get { return File.Exists(AppExePath); }
        }

        /// <summary>注册表里记录的旧安装位置（升级时沿用），没有则 null。</summary>
        public static string StoredInstallLocation
        {
            get { return ReadInstallLocation(); }
        }

        // ---------------- 日志 ----------------

        private static void ResetLog()
        {
            try
            {
                File.WriteAllText(LogPath,
                    "余额兔安装程序 " + Version + "  " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") +
                    Environment.NewLine + "系统：" + Environment.OSVersion + " 用户：" +
                    Environment.UserName + Environment.NewLine, Encoding.UTF8);
            }
            catch
            {
                // 忽略
            }
        }

        private static void Log(string line)
        {
            try
            {
                File.AppendAllText(LogPath, DateTime.Now.ToString("HH:mm:ss ") + line + Environment.NewLine,
                    Encoding.UTF8);
            }
            catch
            {
                // 忽略
            }
        }

        public static string Describe(Exception ex)
        {
            if (ex == null) return "";
            string text = ex.GetType().Name + ": " + ex.Message;
            if (ex.InnerException != null) text += " <- " + Describe(ex.InnerException);
            return text;
        }

        private static void Report(Action<string> progress, string message)
        {
            Log(message);
            if (progress != null) progress(message);
        }
    }
}
