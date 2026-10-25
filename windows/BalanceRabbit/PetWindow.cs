using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace BalanceRabbit
{
    /// <summary>
    /// 桌面上的兔子窗口：只负责「贴图 + 交互」。
    ///
    /// 形象是两张静态 PNG（Assets/pet_sky.png / pet_sky_low.png，与 macOS 版同一份图，
    /// 由 pet/Tools 生成），运行时不画任何矢量路径，所以不会出现某个平台耳朵错位；
    /// 也没有呼吸/眨眼/耳朵摆动/悬停放大等动画。
    /// </summary>
    public sealed class PetWindow : LayeredForm
    {
        private bool dragging;
        private Point dragStartCursor;
        private Point dragStartLocation;

        public event Action Clicked;
        public event Action ContextMenuRequested;
        public event Action DragEnded;
        public event Action<float> ResizeRequested;

        /// <summary>低余额时换成右上角带「!」的那张图</summary>
        public bool LowBalance;
        public int LogicalSize = 176;

        public PetWindow()
        {
            Text = "余额兔";
            Cursor = Cursors.Hand;
        }

        public void SetLogicalSize(int size)
        {
            LogicalSize = Math.Max(96, Math.Min(320, size));
            ApplyLogicalSize(LogicalSize, LogicalSize);
            Render();
        }

        public void Render()
        {
            int pixel = Math.Max(1, (int)Math.Round(LogicalSize * DpiScale));
            if (pixel <= 0) return;
            Graphics g;
            using (Bitmap bitmap = CreateCanvas(pixel, pixel, out g))
            {
                using (g)
                {
                    Image image = LowBalance ? (PetImages.Low ?? PetImages.Normal) : PetImages.Normal;
                    if (image != null)
                    {
                        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                        g.PixelOffsetMode = PixelOffsetMode.HighQuality;
                        g.SmoothingMode = SmoothingMode.HighQuality;
                        g.DrawImage(image, new Rectangle(0, 0, pixel, pixel));
                    }
                }
                Present(bitmap);
            }
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e);
            if (e.Button == MouseButtons.Right)
            {
                if (ContextMenuRequested != null) ContextMenuRequested();
                return;
            }
            if (e.Button != MouseButtons.Left) return;
            dragStartCursor = Cursor.Position;
            dragStartLocation = Location;
            dragging = false;
            Capture = true;
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            base.OnMouseMove(e);
            if (!Capture || e.Button != MouseButtons.Left) return;
            Point current = Cursor.Position;
            int dx = current.X - dragStartCursor.X;
            int dy = current.Y - dragStartCursor.Y;
            if (!dragging && (Math.Abs(dx) > 2 || Math.Abs(dy) > 2)) dragging = true;
            if (!dragging) return;
            Location = new Point(dragStartLocation.X + dx, dragStartLocation.Y + dy);
        }

        protected override void OnMouseUp(MouseEventArgs e)
        {
            base.OnMouseUp(e);
            if (e.Button != MouseButtons.Left) return;
            bool wasDragging = dragging;
            Capture = false;
            dragging = false;
            if (wasDragging)
            {
                if (DragEnded != null) DragEnded();
            }
            else
            {
                if (Clicked != null) Clicked();
            }
        }

        protected override void OnMouseWheel(MouseEventArgs e)
        {
            base.OnMouseWheel(e);
            bool modifier = (ModifierKeys & (Keys.Control | Keys.Alt)) != 0;
            if (!modifier) return;
            float step = e.Delta > 0 ? 12f : -12f;
            if (ResizeRequested != null) ResizeRequested(step);
        }
    }
}
