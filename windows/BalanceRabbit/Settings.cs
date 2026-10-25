using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace BalanceRabbit
{
    /// <summary>本机配置：%APPDATA%\BalanceRabbit\settings.ini（API Key 用 DPAPI 加密）。</summary>
    public sealed class Settings
    {
        private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("BalanceRabbit.v1");

        private readonly Dictionary<string, string> values =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        private readonly string filePath;

        private static string dataDirectory;
        private static bool storageWritable = true;

        /// <summary>默认位置：%APPDATA%\BalanceRabbit。</summary>
        public static string DefaultDataDirectory
        {
            get
            {
                return Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "BalanceRabbit");
            }
        }

        /// <summary>设置/Key 的存放目录。若被安全软件拦截，自动退到程序旁 / 临时目录。</summary>
        public static string DataDirectory
        {
            get
            {
                if (dataDirectory != null) return dataDirectory;
                foreach (string candidate in CandidateDataDirectories())
                {
                    if (!IsWritable(candidate)) continue;
                    dataDirectory = candidate;
                    storageWritable = true;
                    return dataDirectory;
                }
                dataDirectory = DefaultDataDirectory;
                storageWritable = false;
                return dataDirectory;
            }
        }

        /// <summary>本机是否允许写设置；false 表示只能本次运行有效（内存保存）。</summary>
        public static bool StorageWritable
        {
            get
            {
                // 触发一次探测
                var unused = DataDirectory;
                return storageWritable;
            }
        }

        private static IEnumerable<string> CandidateDataDirectories()
        {
            yield return DefaultDataDirectory;

            string exeDirectory = null;
            try
            {
                exeDirectory = Path.GetDirectoryName(Startup.ExecutablePath);
            }
            catch
            {
                // 忽略
            }
            if (!string.IsNullOrEmpty(exeDirectory))
            {
                // 便携模式：程序旁边（下载/桌面/自选目录通常可写）
                yield return Path.Combine(exeDirectory, "BalanceRabbit-data");
            }

            yield return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "BalanceRabbit");
            yield return Path.Combine(Path.GetTempPath(), "BalanceRabbit");
        }

        private static bool IsWritable(string directory)
        {
            try
            {
                Directory.CreateDirectory(directory);
                string probe = Path.Combine(directory, ".write-test-" + Guid.NewGuid().ToString("N"));
                File.WriteAllText(probe, "ok", Encoding.UTF8);
                File.Delete(probe);
                return true;
            }
            catch
            {
                return false;
            }
        }

        public Settings()
        {
            filePath = Path.Combine(DataDirectory, "settings.ini");
            Load();
        }

        private void Load()
        {
            try
            {
                if (!File.Exists(filePath)) return;
                foreach (string rawLine in File.ReadAllLines(filePath, Encoding.UTF8))
                {
                    string line = rawLine.Trim();
                    if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal) ||
                        line.StartsWith(";", StringComparison.Ordinal)) continue;
                    int eq = line.IndexOf('=');
                    if (eq <= 0) continue;
                    string key = line.Substring(0, eq).Trim();
                    string value = line.Substring(eq + 1).Trim();
                    values[key] = value;
                }
            }
            catch
            {
                // 配置损坏时按默认值继续
            }
        }

        public void Save()
        {
            try
            {
                Directory.CreateDirectory(DataDirectory);
                var sb = new StringBuilder();
                sb.AppendLine("# 余额兔设置（可手动编辑，重启生效）");
                foreach (KeyValuePair<string, string> pair in values)
                {
                    sb.Append(pair.Key).Append('=').AppendLine(pair.Value);
                }
                string text = sb.ToString();
                string temp = filePath + ".tmp";
                File.WriteAllText(temp, text, new UTF8Encoding(false));
                if (File.Exists(filePath))
                {
                    try
                    {
                        // 原子替换，避免写到一半崩溃导致 API Key 丢失
                        File.Replace(temp, filePath, filePath + ".bak", true);
                    }
                    catch
                    {
                        try { File.Delete(filePath); } catch { }
                        File.Move(temp, filePath);
                    }
                }
                else
                {
                    File.Move(temp, filePath);
                }
            }
            catch
            {
                // 写配置失败不影响主流程
            }
        }

        public string ConfigPath
        {
            get { return filePath; }
        }

        private string Get(string key, string fallback)
        {
            string value;
            return values.TryGetValue(key, out value) ? value : fallback;
        }

        private int GetInt(string key, int fallback)
        {
            int value;
            return int.TryParse(Get(key, ""), out value) ? value : fallback;
        }

        private double GetDouble(string key, double fallback)
        {
            double value;
            return double.TryParse(Get(key, ""), System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out value) ? value : fallback;
        }

        private void Set(string key, string value)
        {
            values[key] = value ?? "";
        }

        public int RefreshMinutes
        {
            get { return GetInt("refresh_minutes", 10); }
            set { Set("refresh_minutes", value.ToString()); Save(); }
        }

        public double LowThreshold
        {
            get { return GetDouble("low_threshold", 20); }
            set { Set("low_threshold", value.ToString(System.Globalization.CultureInfo.InvariantCulture)); Save(); }
        }

        public int PetSize
        {
            get { return GetInt("pet_size", 176); }
            set { Set("pet_size", value.ToString()); Save(); }
        }

        public int PetX
        {
            get { return GetInt("pet_x", int.MinValue); }
            set { Set("pet_x", value.ToString()); Save(); }
        }

        public int PetY
        {
            get { return GetInt("pet_y", int.MinValue); }
            set { Set("pet_y", value.ToString()); Save(); }
        }

        public bool EdgeDockEnabled
        {
            get { return Get("edge_dock", "1") == "1"; }
            set { Set("edge_dock", value ? "1" : "0"); Save(); }
        }

        public bool PetHidden
        {
            get { return Get("pet_hidden", "0") == "1"; }
            set { Set("pet_hidden", value ? "1" : "0"); Save(); }
        }

        public bool DidWelcome
        {
            get { return Get("did_welcome", "0") == "1"; }
            set { Set("did_welcome", value ? "1" : "0"); Save(); }
        }

        /// <summary>上次运行时的版本号；升级后用来确认「这台电脑是不是换人用了」。</summary>
        public string LastRunVersion
        {
            get { return Get("last_run_version", ""); }
            set { Set("last_run_version", value ?? ""); Save(); }
        }

        /// <summary>DPAPI 加密后的 API Key（BASE64）。</summary>
        public string ApiKey
        {
            get
            {
                string stored = Get("api_key", "");
                if (string.IsNullOrEmpty(stored)) return null;
                try
                {
                    byte[] cipher = Convert.FromBase64String(stored);
                    byte[] plain = ProtectedData.Unprotect(cipher, Entropy, DataProtectionScope.CurrentUser);
                    string key = Encoding.UTF8.GetString(plain).Trim();
                    return key.Length > 0 ? key : null;
                }
                catch
                {
                    return null;
                }
            }
            set
            {
                if (string.IsNullOrEmpty(value))
                {
                    Set("api_key", "");
                }
                else
                {
                    byte[] plain = Encoding.UTF8.GetBytes(value.Trim());
                    byte[] cipher = ProtectedData.Protect(plain, Entropy, DataProtectionScope.CurrentUser);
                    Set("api_key", Convert.ToBase64String(cipher));
                }
                Save();
            }
        }
    }

    /// <summary>API Key 只认本机当前 Windows 用户保存的 Key；不再去读别人的配置文件。</summary>
    public static class Credentials
    {
        private static Settings settings;

        public static Settings Current
        {
            get { return settings ?? (settings = new Settings()); }
        }

        public static void UseSettings(Settings value)
        {
            settings = value;
        }

        public static string ResolveApiKey()
        {
            string saved = Current.ApiKey;
            if (!string.IsNullOrWhiteSpace(saved)) return saved.Trim();

            // 仅供本机调试：显式设置了环境变量才用；绝不读取他人的配置文件。
            string env = Environment.GetEnvironmentVariable("RABBIT_API_KEY");
            if (!string.IsNullOrWhiteSpace(env)) return env.Trim();

            return null;
        }

        public static bool HasKey
        {
            get { return !string.IsNullOrWhiteSpace(ResolveApiKey()); }
        }

        /// <summary>给用户看 Key 尾号，便于确认当前用的是哪个账号的 Key。</summary>
        public static string KeyHint
        {
            get
            {
                string key = ResolveApiKey();
                if (string.IsNullOrEmpty(key)) return "";
                if (key.Length <= 4) return key;
                return "…" + key.Substring(key.Length - 4);
            }
        }
    }

    /// <summary>开机自启（HKCU Run）。</summary>
    public static class Startup
    {
        private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string ValueName = "BalanceRabbit";

        public static string ExecutablePath
        {
            get
            {
                try
                {
                    return System.Reflection.Assembly.GetEntryAssembly().Location;
                }
                catch
                {
                    return System.Diagnostics.Process.GetCurrentProcess().MainModule.FileName;
                }
            }
        }

        public static bool IsEnabled()
        {
            try
            {
                using (var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(RunKey, false))
                {
                    if (key == null) return false;
                    var value = key.GetValue(ValueName) as string;
                    if (string.IsNullOrEmpty(value)) return false;
                    string path = value.Trim();
                    if (path.Length >= 2 && path[0] == '"' && path[path.Length - 1] == '"')
                    {
                        path = path.Substring(1, path.Length - 2);
                    }
                    try
                    {
                        // 路径对不上说明是搬家/绿色版留下的旧值，不能显示为已启用
                        return string.Equals(Path.GetFullPath(path),
                            Path.GetFullPath(ExecutablePath), StringComparison.OrdinalIgnoreCase);
                    }
                    catch
                    {
                        return false;
                    }
                }
            }
            catch
            {
                return false;
            }
        }

        public static bool Enable()
        {
            try
            {
                using (var key = Microsoft.Win32.Registry.CurrentUser.CreateSubKey(RunKey))
                {
                    if (key == null) return false;
                    key.SetValue(ValueName, "\"" + ExecutablePath + "\"");
                }
                return true;
            }
            catch
            {
                return false;
            }
        }

        public static void Disable()
        {
            try
            {
                using (var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(RunKey, true))
                {
                    if (key != null) key.DeleteValue(ValueName, false);
                }
            }
            catch
            {
                // 忽略
            }
        }
    }
}
