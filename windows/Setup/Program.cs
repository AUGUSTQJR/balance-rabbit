using System;
using System.Windows.Forms;

namespace BalanceRabbit.Setup
{
    internal static class Program
    {
        [STAThread]
        private static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            try
            {
                // 不让卸载/安装进程的工作目录落在安装目录里，否则 rmdir 删不掉自己
                System.IO.Directory.SetCurrentDirectory(System.IO.Path.GetTempPath());
            }
            catch
            {
                // 忽略
            }

            bool uninstall = HasArgument(args, "/uninstall") || HasArgument(args, "--uninstall") ||
                             HasArgument(args, "-u");
            bool silent = HasArgument(args, "/S") || HasArgument(args, "/s") ||
                          HasArgument(args, "/silent") || HasArgument(args, "/quiet");

            if (uninstall)
            {
                RunUninstall(silent);
                return;
            }

            if (silent)
            {
                try
                {
                    Installer.Install(false, Installer.StoredInstallLocation, null);
                }
                catch
                {
                    // 静默安装失败时不弹窗
                }
                return;
            }

            Application.Run(new InstallerForm());
        }

        private static void RunUninstall(bool silent)
        {
            if (!silent)
            {
                DialogResult answer = MessageBox.Show(
                    "确定要卸载「余额兔」吗？\n\n" +
                    "· 会删除程序、桌面与开始菜单快捷方式、开机自启项\n" +
                    "· 会保留 %APPDATA%\\BalanceRabbit 下的设置（含加密的 API Key），" +
                    "重装后不必重新填写\n\n" +
                    "如需彻底清空，卸载后手动删除该文件夹即可。",
                    "卸载余额兔",
                    MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question,
                    MessageBoxDefaultButton.Button2);
                if (answer != DialogResult.Yes) return;
            }

            try
            {
                Installer.Uninstall(silent, null);
                if (!silent)
                {
                    MessageBox.Show("余额兔已卸载。\n\n设置文件保留在 %APPDATA%\\BalanceRabbit，" +
                                    "不需要可直接删除。",
                        "卸载完成", MessageBoxButtons.OK, MessageBoxIcon.Information);
                }
                Installer.FinishRemoval();
            }
            catch (Exception ex)
            {
                if (!silent)
                {
                    MessageBox.Show("卸载时出现问题：\n" + ex.Message, "卸载余额兔",
                        MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            }
        }

        private static bool HasArgument(string[] args, string expected)
        {
            foreach (string arg in args)
            {
                if (string.Equals(arg, expected, StringComparison.OrdinalIgnoreCase)) return true;
            }
            return false;
        }
    }
}
