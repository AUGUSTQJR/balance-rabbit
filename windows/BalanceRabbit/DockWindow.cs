using System;
using System.Drawing;
using System.Windows.Forms;

namespace BalanceRabbit
{
    /// <summary>吸附指示器窗口：只露一半，悬停外探，点击弹回大兔子，可沿边缘上下拖动。</summary>
    public sealed class DockWindow : LayeredForm
    {
        private readonly Timer animation;
        private double phase;
        private bool hovering;
        private bool dragging;
        private Point dragStartCursor;
        private bool dragged;

        public DockEdge Edge = DockEdge.Left;

        public event Action Clicked;
        public event Action ContextMenuRequested;
        public event Action<int> DragMoved;
        public event Action DragEnded;
        public event Action<bool> HoverChanged;

        public DockWindow()
        {
            Text = "余额兔 · 边缘";
            Cursor = Cursors.Hand;
            ApplyLogicalSize((int)DockPainter.LogicalSize, (int)DockPainter.LogicalSize);
            animation = new Timer();
            animation.Interval = 33; // ~30fps
            animation.Tick += (sender, args) =>
            {
                if (!Visible) return;
                phase += 1.0 / 30.0;
                Render();
            };
            animation.Start();
        }

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            animation.Stop();
            animation.Dispose();
            base.OnFormClosed(e);
        }

        public void SetEdge(DockEdge edge)
        {
            Edge = edge;
            Render();
        }

        public void Render()
        {
            float scale = DpiScale;
            int pixel = Math.Max(1, (int)Math.Round(DockPainter.LogicalSize * scale));
            Graphics g;
            using (Bitmap bitmap = CreateCanvas(pixel, pixel, out g))
            {
                using (g)
                {
                    DockPainter.Draw(g, pixel, Edge, phase, hovering || dragging);
                }
                Present(bitmap);
            }
        }

        protected override void OnMouseEnter(EventArgs e)
        {
            base.OnMouseEnter(e);
            hovering = true;
            if (HoverChanged != null) HoverChanged(true);
            Render();
        }

        protected override void OnMouseLeave(EventArgs e)
        {
            base.OnMouseLeave(e);
            hovering = false;
            if (HoverChanged != null) HoverChanged(false);
            Render();
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
            dragging = false;
            dragged = false;
            Capture = true;
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            base.OnMouseMove(e);
            if (!Capture || e.Button != MouseButtons.Left) return;
            Point current = Cursor.Position;
            int dy = current.Y - dragStartCursor.Y;
            if (!dragging && Math.Abs(dy) > 2) dragging = true;
            if (!dragging) return;
            dragged = true;
            if (DragMoved != null) DragMoved(dy);
            dragStartCursor = current;
        }

        protected override void OnMouseUp(MouseEventArgs e)
        {
            base.OnMouseUp(e);
            if (e.Button != MouseButtons.Left) return;
            Capture = false;
            bool wasDragging = dragged;
            dragging = false;
            dragged = false;
            if (wasDragging)
            {
                if (DragEnded != null) DragEnded();
            }
            else
            {
                if (Clicked != null) Clicked();
            }
        }
    }
}
