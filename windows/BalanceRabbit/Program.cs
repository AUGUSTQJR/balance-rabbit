using System;
using System.IO;
using System.Threading;
using System.Windows.Forms;

namespace BalanceRabbit
{
    internal static class Program
    {
        private const string MutexName = "Local\\BalanceRabbit.SingleInstance";
        private const string ShowEventName = "Local\\BalanceRabbit.Show";

        [STAThread]
        private static void Main()
        {
            bool created;
            using (var mutex = new Mutex(true, MutexName, out created))
            {
                if (!created)
                {
                    SignalExistingInstance();
                    return;
                }

                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
                Application.ThreadException += OnThreadException;

                EventWaitHandle showEvent = null;
                try
                {
                    showEvent = new EventWaitHandle(false, EventResetMode.AutoReset, ShowEventName);
                }
                catch
                {
                    // 无法创建事件时退化为单实例无唤醒
                }

                using (var app = new App(showEvent))
                {
                    app.BeginStartup();
                    Application.Run(app);
                }
            }
        }

        private static bool reportedError;

        private static void OnThreadException(object sender, ThreadExceptionEventArgs e)
        {
            try
            {
                string dir = Settings.DataDirectory;
                Directory.CreateDirectory(dir);
                File.AppendAllText(Path.Combine(dir, "error.log"),
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + Environment.NewLine +
                    e.Exception + Environment.NewLine + Environment.NewLine);
            }
            catch
            {
                // 忽略
            }

            if (reportedError) return;
            reportedError = true;
            try
            {
                MessageBox.Show(
                    "余额兔遇到一个错误，已记录到 %APPDATA%\\BalanceRabbit\\error.log：\n\n" +
                    e.Exception.Message,
                    "余额兔", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            catch
            {
                // 忽略
            }
        }

        private static void SignalExistingInstance()
        {
            try
            {
                using (var handle = EventWaitHandle.OpenExisting(ShowEventName))
                {
                    handle.Set();
                }
            }
            catch
            {
                // 老实例尚未就绪，忽略
            }
        }
    }
}
