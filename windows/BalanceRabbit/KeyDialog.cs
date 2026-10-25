using System;
using System.Drawing;
using System.Windows.Forms;

namespace BalanceRabbit
{
    /// <summary>设置 API Key 的小对话框。</summary>
    public sealed class KeyDialog : Form
    {
        private readonly TextBox input;

        public string ApiKey
        {
            get { return input.Text.Trim(); }
        }

        public KeyDialog(string current)
        {
            Text = "设置你自己的 API Key";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;
            ShowInTaskbar = false;
            TopMost = true;
            ClientSize = new Size(460, 236);
            Font = new Font("Microsoft YaHei UI", 9f);

            var title = new Label();
            title.Text = "填写你自己的 rabbitj.top API Key";
            title.Font = new Font("Microsoft YaHei UI", 11f, FontStyle.Bold);
            title.AutoSize = true;
            title.Location = new Point(20, 16);
            Controls.Add(title);

            var hint = new Label();
            hint.Text = "每个 Windows 用户 / 每台电脑都要填自己的 Key。\n" +
                        "填了别人的 Key 就会显示别人的余额，请勿混用。\n" +
                        "Key 只保存在本机（Windows DPAPI 加密），不会上传。";
            hint.AutoSize = true;
            hint.ForeColor = Color.FromArgb(102, 102, 102);
            hint.Location = new Point(20, 46);
            Controls.Add(hint);

            input = new TextBox();
            input.Location = new Point(20, 122);
            input.Width = 420;
            input.UseSystemPasswordChar = false;
            input.Text = current ?? "";
            Controls.Add(input);

            var save = new Button();
            save.Text = "保存";
            save.DialogResult = DialogResult.OK;
            save.Location = new Point(270, 174);
            save.Width = 80;
            save.Height = 30;
            Controls.Add(save);

            var cancel = new Button();
            cancel.Text = "取消";
            cancel.DialogResult = DialogResult.Cancel;
            cancel.Location = new Point(360, 174);
            cancel.Width = 80;
            cancel.Height = 30;
            Controls.Add(cancel);

            AcceptButton = save;
            CancelButton = cancel;
        }

        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            Activate();
            BringToFront();
            input.Focus();
            input.SelectAll();
        }
    }
}
