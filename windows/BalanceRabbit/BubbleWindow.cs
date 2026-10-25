using System;
using System.Drawing;
using System.Windows.Forms;

namespace BalanceRabbit
{
    /// <summary>余额气泡窗口：轻点无操作，左键刷新，右键菜单。</summary>
    public sealed class BubbleWindow : LayeredForm
    {
        private Stats stats;
        private bool loading;
        private float tailX = 150f;
        private bool tailUp;
        private int hoverDay = -1;
        private int selectedDay = -1;

        public double LowThreshold = 20;

        public event Action RefreshRequested;
        public event Action ContextMenuRequested;

        public BubbleWindow()
        {
            Text = "余额兔 · 余额";
            Cursor = Cursors.Hand;
            ApplyLogicalSize((int)BubblePainter.DesignWidth, (int)BubblePainter.DesignHeight);
        }

        public void SetState(Stats value, bool isLoading)
        {
            stats = value;
            loading = isLoading;
        }

        /// <summary>刷新成功后清掉柱状图的悬停 / 选中状态（和 macOS 版一致）。</summary>
        public void ResetInteraction()
        {
            hoverDay = -1;
            selectedDay = -1;
        }

        public void Render()
        {
            float scale = DpiScale;
            int width = Math.Max(1, (int)Math.Round(BubblePainter.DesignWidth * scale));
            int height = Math.Max(1, (int)Math.Round(BubblePainter.DesignHeight * scale));
            if (Size.Width != width || Size.Height != height) Size = new Size(width, height);

            Graphics g;
            using (Bitmap bitmap = CreateCanvas(width, height, out g))
            {
                using (g)
                {
                    BubblePainter.Draw(g, width, height, stats, loading, tailX, tailUp, LowThreshold,
                        hoverDay, selectedDay);
                }
                Present(bitmap);
            }
        }

        public void ShowAt(Point location, float tailDesignX, bool tailUpward)
        {
            tailX = Math.Max(26f, Math.Min(BubblePainter.DesignWidth - 26f, tailDesignX));
            tailUp = tailUpward;
            Location = location;
            Render();
            if (!Visible) Show();
            BringToFront();
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e);
            if (e.Button == MouseButtons.Right)
            {
                if (ContextMenuRequested != null) ContextMenuRequested();
                return;
            }

            if (e.Button == MouseButtons.Left)
            {
                int day = DayAt(e.Location);
                if (day >= 0)
                {
                    // 点柱子：显示该日花费，再点一次取消
                    selectedDay = selectedDay == day ? -1 : day;
                    hoverDay = day;
                    Render();
                    return;
                }

                if (RefreshRequested != null) RefreshRequested();
            }
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            base.OnMouseMove(e);
            int day = DayAt(e.Location);
            if (day != hoverDay)
            {
                hoverDay = day;
                Cursor = day >= 0 ? Cursors.Hand : Cursors.Default;
                Render();
            }
        }

        protected override void OnVisibleChanged(EventArgs e)
        {
            base.OnVisibleChanged(e);
            if (!Visible)
            {
                hoverDay = -1;
                selectedDay = -1;
                Cursor = Cursors.Default;
            }
        }

        protected override void OnMouseLeave(EventArgs e)
        {
            base.OnMouseLeave(e);
            if (hoverDay != -1)
            {
                hoverDay = -1;
                Cursor = Cursors.Default;
                Render();
            }
        }

        /// <summary>命中的柱状图日索引；-1 表示没点在图表上。</summary>
        private int DayAt(Point client)
        {
            float scale = DpiScale;
            if (scale <= 0.1f) scale = 1f;
            float x = client.X / scale;
            float y = client.Y / scale;

            float cardTop = tailUp ? 20f : 2f;
            float chartTop = cardTop + BubblePainter.ChartTopOffset;
            float baseline = chartTop + BubblePainter.ChartBarHeight;

            if (x < BubblePainter.ChartLeft || x > BubblePainter.ChartLeft + BubblePainter.ChartWidth) return -1;
            if (y < chartTop - 4f || y > baseline + 16f) return -1;
            if (stats == null || stats.Daily == null || stats.Daily.Count == 0) return -1;

            float slot = BubblePainter.ChartWidth / BubblePainter.DayCount;
            int index = (int)((x - BubblePainter.ChartLeft) / slot);
            if (index < 0) index = 0;
            if (index >= stats.Daily.Count) index = stats.Daily.Count - 1;
            return index;
        }

        // 卡片范围内一律算作窗口内容：不让点击穿透到背后的窗口
        private const int WM_NCHITTEST = 0x0084;
        private const int HTCLIENT = 1;
        private const int HTTRANSPARENT = -1;

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == WM_NCHITTEST)
            {
                long lp = m.LParam.ToInt64();
                int screenX = unchecked((short)(lp & 0xFFFF));
                int screenY = unchecked((short)((lp >> 16) & 0xFFFF));
                Point client = PointToClient(new Point(screenX, screenY));

                float scale = DpiScale;
                if (scale <= 0.1f) scale = 1f;
                float x = client.X / scale;
                float y = client.Y / scale;

                float cardTop = tailUp ? 20f : 2f;
                bool insideCard = x >= 2f && x <= 298f && y >= cardTop && y <= cardTop + 256f;
                bool insideTail = y > cardTop + 256f && y <= cardTop + 256f + 15f &&
                                  Math.Abs(x - tailX) <= 12f;
                m.Result = (IntPtr)(insideCard || insideTail ? HTCLIENT : HTTRANSPARENT);
                return;
            }
            base.WndProc(ref m);
        }
    }
}
