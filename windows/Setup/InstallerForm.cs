using System;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace BalanceRabbit.Setup
{
    /// <summary>安装向导：一屏完成安装。</summary>
    public sealed class InstallerForm : Form
    {
        private Label pathLabel;
        private string targetDirectory;
        private readonly CheckBox startupBox;
        private readonly CheckBox launchBox;
        private readonly Label statusLabel;
        private readonly ProgressBar progressBar;
        private readonly Button installButton;
        private readonly Button closeButton;
        private bool installing;
        private bool installed;

        public InstallerForm()
        {
            Text = "余额兔 · Windows 安装程序";
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(600, 400);
            BackColor = Color.White;
            Font = new Font("Microsoft YaHei UI", 9f);
            Icon = LoadIcon();

            var title = new Label();
            title.Text = "余额兔";
            title.Font = new Font("Microsoft YaHei UI", 22f, FontStyle.Bold);
            title.ForeColor = Color.FromArgb(52, 45, 40);
            title.AutoSize = true;
            title.Location = new Point(30, 26);
            Controls.Add(title);

            var subtitle = new Label();
            subtitle.Text = "Windows 桌面余额宠物 · 点一下看余额";
            subtitle.Font = new Font("Microsoft YaHei UI", 11f);
            subtitle.ForeColor = Color.FromArgb(120, 110, 102);
            subtitle.AutoSize = true;
            subtitle.Location = new Point(33, 74);
            Controls.Add(subtitle);

            var version = new Label();
            version.Text = "版本 " + Installer.Version + " · 安装到当前用户，可自选安装位置" +
                           (Installer.IsInstalled ? " · 已检测到旧版本，将覆盖升级" : "");
            version.ForeColor = Color.FromArgb(140, 132, 125);
            version.AutoSize = true;
            version.Location = new Point(33, 106);
            Controls.Add(version);

            targetDirectory = Installer.InstallDir;

            pathLabel = new Label();
            pathLabel.Text = "安装位置：" + targetDirectory;
            pathLabel.ForeColor = Color.FromArgb(90, 84, 78);
            pathLabel.AutoEllipsis = true;
            pathLabel.AutoSize = false;
            pathLabel.Location = new Point(33, 132);
            pathLabel.Size = new Size(420, 20);
            Controls.Add(pathLabel);

            var browseButton = new Button();
            browseButton.Text = "更改安装位置…";
            browseButton.Location = new Point(458, 127);
            browseButton.Size = new Size(115, 28);
            browseButton.Click += OnBrowseClicked;
            Controls.Add(browseButton);

            var line = new Label();
            line.BorderStyle = BorderStyle.Fixed3D;
            line.AutoSize = false;
            line.Location = new Point(30, 164);
            line.Size = new Size(540, 2);
            Controls.Add(line);

            startupBox = new CheckBox();
            startupBox.Text = "开机自动启动（推荐，常驻托盘）";
            // 升级安装时尊重用户之前在程序里关掉自启的选择
            startupBox.Checked = !Installer.IsInstalled || Installer.IsStartupEnabled();
            startupBox.AutoSize = true;
            startupBox.Location = new Point(33, 182);
            Controls.Add(startupBox);

            launchBox = new CheckBox();
            launchBox.Text = "安装完成后立即运行余额兔";
            launchBox.Checked = true;
            launchBox.AutoSize = true;
            launchBox.Location = new Point(33, 210);
            Controls.Add(launchBox);

            statusLabel = new Label();
            statusLabel.Text = "准备就绪，点「安装」开始。";
            statusLabel.ForeColor = Color.FromArgb(90, 84, 78);
            statusLabel.AutoEllipsis = true;
            statusLabel.Location = new Point(33, 254);
            statusLabel.Size = new Size(535, 22);
            Controls.Add(statusLabel);

            progressBar = new ProgressBar();
            progressBar.Location = new Point(33, 280);
            progressBar.Size = new Size(535, 6);
            progressBar.Style = ProgressBarStyle.Continuous;
            progressBar.Minimum = 0;
            progressBar.Maximum = 100;
            progressBar.Value = 0;
            Controls.Add(progressBar);

            installButton = new Button();
            installButton.Text = "安装";
            installButton.Font = new Font("Microsoft YaHei UI", 10f, FontStyle.Bold);
            installButton.Location = new Point(438, 316);
            installButton.Size = new Size(130, 42);
            installButton.Click += OnInstallClicked;
            Controls.Add(installButton);

            closeButton = new Button();
            closeButton.Text = "取消";
            closeButton.Location = new Point(318, 316);
            closeButton.Size = new Size(108, 42);
            closeButton.Click += OnCloseClicked;
            Controls.Add(closeButton);

            AcceptButton = installButton;
            CancelButton = closeButton;
            FormClosing += delegate(object sender, FormClosingEventArgs args)
            {
                if (installing) args.Cancel = true;
            };
        }

        private static Icon LoadIcon()
        {
            try
            {
                using (var stream = typeof(InstallerForm).Assembly
                    .GetManifestResourceStream("Setup.icon.ico"))
                {
                    if (stream != null) return new Icon(stream);
                }
            }
            catch
            {
                // 忽略
            }
            return SystemIcons.Application;
        }

        private void OnBrowseClicked(object sender, EventArgs e)
        {
            using (var dialog = new FolderBrowserDialog())
            {
                dialog.Description = "选择安装位置：程序会安装到所选文件夹下的 BalanceRabbit 子文件夹";
                dialog.ShowNewFolderButton = true;
                try
                {
                    dialog.SelectedPath = System.IO.Path.GetDirectoryName(targetDirectory);
                }
                catch
                {
                    // 忽略
                }
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                targetDirectory = Installer.ResolveTargetFromSelection(dialog.SelectedPath);
                pathLabel.Text = "安装位置：" + targetDirectory;
            }
        }

        private void OnCloseClicked(object sender, EventArgs e)
        {
            if (installing) return;
            Close();
        }

        private async void OnInstallClicked(object sender, EventArgs e)
        {
            if (installing) return;
            if (installed)
            {
                Close();
                return;
            }

            installing = true;
            installButton.Enabled = false;
            closeButton.Enabled = false;
            startupBox.Enabled = false;
            launchBox.Enabled = false;
            progressBar.Value = 8;
            statusLabel.Text = "开始安装…";

            bool createStartup = startupBox.Checked;
            IProgress<string> progress = new Progress<string>(message =>
            {
                statusLabel.Text = message;
                if (progressBar.Value < 90) progressBar.Value += 12;
            });

            string error = null;
            try
            {
                await Task.Run(() => Installer.Install(createStartup, targetDirectory, progress.Report));
                progressBar.Value = 100;
                installed = true;
                statusLabel.Text = "安装完成，位置：" + Installer.InstallDir;

                if (launchBox.Checked) Installer.LaunchApp();

                installButton.Text = "关闭";
                installButton.Enabled = true;
                closeButton.Visible = false;
                AcceptButton = installButton;
                installing = false;
                return;
            }
            catch (Exception ex)
            {
                error = ex.Message;
            }

            installing = false;
            installButton.Enabled = true;
            closeButton.Enabled = true;
            startupBox.Enabled = true;
            launchBox.Enabled = true;
            progressBar.Value = 0;
            statusLabel.Text = "安装失败，见弹出的提示。";

            DialogResult retry = MessageBox.Show(this,
                "安装失败：\n" + error +
                "\n\n常见原因：安全软件（360 / 火绒 / 公司终端防护）拦截写入、目录权限不足，" +
                "或旧版本文件正被占用。\n\n安装日志：" + Installer.LogPath +
                "\n\n是否尝试「以管理员身份」重新运行安装程序？\n" +
                "（如果仍失败，可改用绿色版 zip：解压到「下载」或桌面，双击 BalanceRabbit.exe 直接运行）",
                "余额兔安装程序",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Error,
                MessageBoxDefaultButton.Button2);

            if (retry == DialogResult.Yes)
            {
                try
                {
                    var info = new System.Diagnostics.ProcessStartInfo(Application.ExecutablePath);
                    info.UseShellExecute = true;
                    info.Verb = "runas";
                    System.Diagnostics.Process.Start(info);
                    Close();
                }
                catch
                {
                    // 用户取消了 UAC 或系统不允许提权
                }
            }
        }
    }
}
