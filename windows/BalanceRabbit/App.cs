using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using Timer = System.Windows.Forms.Timer;

namespace BalanceRabbit
{
    /// <summary>应用主控制器：托盘、菜单、定时刷新、气泡、吸附。</summary>
    public sealed class App : ApplicationContext
    {
        private readonly Settings settings;
        private readonly APIClient api = new APIClient();
        private readonly NotifyIcon tray;
        private readonly PetWindow pet;
        private readonly BubbleWindow bubble;
        private readonly DockWindow dock;
        private readonly Icon trayIcon;

        private readonly Timer refreshTimer;
        private readonly Timer bubbleTimer;
        private readonly Timer trayClickTimer;
        private EventHandler systemEventsHandler;
        private readonly EventWaitHandle showEvent;

        private Stats stats;
        private bool refreshing;
        private DateTime lastLowNotify = DateTime.MinValue;
        private DateTime bubbleShownAt = DateTime.MinValue;
        private bool showBubbleAfterRefresh;

        private bool docked;
        private DockEdge dockEdge = DockEdge.Left;
        private int dockAnchor;
        private bool dockExpanded;
        private Rectangle dockWorkArea;

        public App(EventWaitHandle showEvent)
        {
            this.showEvent = showEvent;
            settings = new Settings();
            Credentials.UseSettings(settings);

            trayIcon = LoadIcon();
            tray = new NotifyIcon();
            tray.Icon = trayIcon;
            tray.Text = "余额兔";
            tray.Visible = true;
            tray.MouseClick += OnTrayClick;
            tray.MouseDoubleClick += OnTrayDoubleClick;
            tray.ContextMenuStrip = BuildMenu();

            pet = new PetWindow();
            pet.Clicked += ToggleBubble;
            pet.ContextMenuRequested += ShowContextMenu;
            pet.DragEnded += OnPetDragEnded;
            pet.ResizeRequested += OnPetResizeRequested;
            pet.LowBalance = false;

            bubble = new BubbleWindow();
            bubble.RefreshRequested += delegate { Refresh(true); };
            bubble.ContextMenuRequested += ShowContextMenu;

            dock = new DockWindow();
            dock.Clicked += Undock;
            dock.ContextMenuRequested += ShowContextMenu;
            dock.DragMoved += OnDockDragMoved;
            dock.HoverChanged += OnDockHoverChanged;

            refreshTimer = new Timer();
            refreshTimer.Tick += delegate { Refresh(false); };

            bubbleTimer = new Timer();
            bubbleTimer.Interval = 1000;
            bubbleTimer.Tick += OnBubbleTimer;
            bubbleTimer.Start();

            trayClickTimer = new Timer();
            trayClickTimer.Interval = Math.Max(250, SystemInformation.DoubleClickTime);
            trayClickTimer.Tick += delegate
            {
                trayClickTimer.Stop();
                ToggleBubble();
            };

            CreatePet();
            StartShowListener();
            ApplyRefreshTimer();

            try
            {
                systemEventsHandler = delegate
                {
                    try
                    {
                        if (!pet.IsDisposed && pet.IsHandleCreated)
                        {
                            pet.BeginInvoke(new Action(HandleDisplayChanged));
                        }
                    }
                    catch
                    {
                        // 忽略
                    }
                };
                Microsoft.Win32.SystemEvents.DisplaySettingsChanged += systemEventsHandler;
            }
            catch
            {
                // 忽略
            }
        }

        /// <summary>消息循环启动后调用：首次运行引导填写 Key，然后拉一次余额。</summary>
        public void BeginStartup()
        {
            var startupTimer = new Timer();
            startupTimer.Interval = 250;
            startupTimer.Tick += delegate
            {
                startupTimer.Stop();
                startupTimer.Dispose();

                if (!Settings.StorageWritable)
                {
                    try
                    {
                        tray.ShowBalloonTip(8000, "余额兔",
                            "当前安全策略禁止写入设置文件，API Key 与设置只能本次运行有效。" +
                            "建议把 BalanceRabbit.exe 放到下载 / 桌面 / D 盘等可写目录，或让安全软件放行。",
                            ToolTipIcon.Warning);
                    }
                    catch
                    {
                        // 忽略
                    }
                }

                RunFirstRunSetup();
                showBubbleAfterRefresh = true;
                Refresh(false);
            };
            startupTimer.Start();
        }

        private static string AppDataMarkerPath
        {
            get
            {
                return Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "BalanceRabbit", "just-installed.txt");
            }
        }

        private static string AppVersion()
        {
            Version version = Assembly.GetExecutingAssembly().GetName().Version;
            return version == null ? "1.2.0" : version.ToString(3);
        }

        /// <summary>
        /// 首次启动 / 升级后确认「这台电脑 / 这个 Windows 用户该用谁的 Key」。
        /// 升级判断用 last_run_version，安装包标记只是补充（没写权限时也能识别）。
        /// </summary>
        private void RunFirstRunSetup()
        {
            bool freshInstall = ConsumeInstallMarker();
            bool versionChanged = !string.Equals(settings.LastRunVersion, AppVersion(),
                StringComparison.Ordinal);
            settings.LastRunVersion = AppVersion();

            if (!Credentials.HasKey)
            {
                ShowKeyDialog(true);
                return;
            }

            if (!freshInstall && !versionChanged) return;

            DialogResult answer = MessageBox.Show(
                "这台电脑刚安装 / 更新了余额兔。\n\n" +
                "检测到本机已保存 API Key（尾号 " + Credentials.KeyHint + "）。\n" +
                "如果这台电脑现在换别人使用，继续用这个 Key 会显示原来账号的余额。\n\n" +
                "要继续使用这个 Key 吗？\n" +
                "· 点「是」：继续使用（升级 / 还是我自己的电脑）\n" +
                "· 点「否」：重新填写我自己的 API Key",
                "余额兔 · 确认账号",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question,
                MessageBoxDefaultButton.Button2);
            if (answer == DialogResult.No)
            {
                ShowKeyDialog(false);
            }
        }

        private bool ConsumeInstallMarker()
        {
            string[] candidates =
            {
                AppDataMarkerPath,
                Path.Combine(Settings.DataDirectory, "just-installed.txt")
            };
            foreach (string candidate in candidates)
            {
                try
                {
                    if (!File.Exists(candidate)) continue;
                    File.Delete(candidate);
                    return true;
                }
                catch
                {
                    // 忽略，看下一个位置
                }
            }
            return false;
        }

        // ---------- 启动 / 托盘 ----------

        private static Icon LoadIcon()
        {
            try
            {
                Assembly asm = Assembly.GetExecutingAssembly();
                using (Stream stream = asm.GetManifestResourceStream("BalanceRabbit.icon.ico"))
                {
                    if (stream != null) return new Icon(stream, SystemInformation.SmallIconSize);
                }
            }
            catch
            {
                // 忽略，使用默认图标
            }
            return SystemIcons.Application;
        }

        private void CreatePet()
        {
            settings.PetSize = Math.Max(96, Math.Min(320, settings.PetSize));
            pet.SetLogicalSize(settings.PetSize);
            float scale = pet.DpiScale;

            Point location = new Point(int.MinValue, int.MinValue);
            if (settings.PetX != int.MinValue && settings.PetY != int.MinValue)
            {
                location = new Point(settings.PetX, settings.PetY);
                var rect = new Rectangle(location, new Size(
                    (int)Math.Round(settings.PetSize * scale),
                    (int)Math.Round(settings.PetSize * scale)));
                if (!Screen.AllScreens.AnyScreenContains(rect))
                {
                    location = new Point(int.MinValue, int.MinValue);
                }
            }

            if (location.X == int.MinValue)
            {
                Rectangle work = Screen.PrimaryScreen.WorkingArea;
                float targetScale = LayeredForm.ScaleForRectangle(work);
                pet.Size = new Size(
                    (int)Math.Round(settings.PetSize * targetScale),
                    (int)Math.Round(settings.PetSize * targetScale));
                location = new Point(work.Right - pet.Width - 36, work.Bottom - pet.Height - 24);
            }

            pet.Location = location;
            pet.Show();
            if (!settings.PetHidden)
            {
                pet.Render();
            }
            else
            {
                pet.Hide();
            }
        }

        private void StartShowListener()
        {
            if (showEvent == null) return;
            var thread = new Thread(() =>
            {
                try
                {
                    while (true)
                    {
                        if (!showEvent.WaitOne()) break;
                        try
                        {
                            if (pet.IsDisposed) break;
                            pet.BeginInvoke(new Action(ShowFromSecondInstance));
                        }
                        catch
                        {
                            break;
                        }
                    }
                }
                catch
                {
                    // 退出
                }
            });
            thread.IsBackground = true;
            thread.Start();
        }

        private void ShowFromSecondInstance()
        {
            ShowPetAnywhere();
            ShowBubble();
            Refresh(false);
        }

        // ---------- 查询 ----------

        private async void Refresh(bool showBubbleWhenDone)
        {
            if (refreshing) return;
            refreshing = true;
            if (bubble.Visible)
            {
                bubble.SetState(stats, true);
                bubble.Render();
            }

            try
            {
                string key = Credentials.ResolveApiKey();
                if (string.IsNullOrEmpty(key)) throw ApiException.MissingKey();
                Stats result = await api.LoadStatsAsync(key);
                stats = result;
                stats.Error = null;
                pet.LowBalance = settings.LowThreshold > 0 && stats.IsLow(settings.LowThreshold);
                bubble.LowThreshold = settings.LowThreshold;
                bubble.ResetInteraction();
                bubble.SetState(stats, false);
                UpdateTrayText();
                CheckLowBalance(stats);
                if (showBubbleWhenDone) ShowBubble();
                else if (bubble.Visible) bubble.Render();
            }
            catch (Exception ex)
            {
                var apiError = ex as ApiException;
                string message = apiError != null ? apiError.Message : ex.Message;
                Stats previous = stats;
                stats = new Stats();
                stats.Error = message;
                stats.UpdatedAt = DateTime.Now;
                if (previous != null)
                {
                    // 网络抖动时保留上一次的余额 / 统计，托盘不显示成空
                    stats.Balance = previous.Balance;
                    stats.BalanceAt = previous.BalanceAt;
                    stats.TodaySpend = previous.TodaySpend;
                    stats.TodayRequests = previous.TodayRequests;
                    stats.WeekSpend = previous.WeekSpend;
                    stats.WeekRequests = previous.WeekRequests;
                    stats.WeekTokens = previous.WeekTokens;
                    stats.TotalRequests = previous.TotalRequests;
                    stats.Daily = previous.Daily;
                    stats.TopModels = previous.TopModels;
                    stats.Partial = previous.Partial;
                    stats.AccountUserId = previous.AccountUserId;
                    stats.MultipleAccounts = previous.MultipleAccounts;
                    stats.AccountInactive = previous.AccountInactive;
                    stats.WeekRecharged = previous.WeekRecharged;
                    stats.DataSource = previous.DataSource;
                    stats.BalanceFromAPI = previous.BalanceFromAPI;
                }
                pet.LowBalance = settings.LowThreshold > 0 && stats.IsLow(settings.LowThreshold);
                bubble.SetState(stats, false);
                UpdateTrayText();
                if (showBubbleWhenDone) ShowBubble();
                else if (bubble.Visible) bubble.Render();
            }
            finally
            {
                refreshing = false;
                pet.Render();
                if (showBubbleAfterRefresh)
                {
                    showBubbleAfterRefresh = false;
                    ShowBubble();
                }
            }
        }

        private void UpdateTrayText()
        {
            string text;
            if (stats != null && stats.Balance.HasValue)
            {
                bool low = settings.LowThreshold > 0 && stats.IsLow(settings.LowThreshold);
                text = (low ? "⚠ " : "") + "余额兔 " + Format.Money2(stats.Balance.Value) +
                       " · " + Format.Time(stats.UpdatedAt) + " 更新";
            }
            else if (stats != null && !string.IsNullOrEmpty(stats.Error))
            {
                text = "余额兔 · " + stats.Error;
            }
            else
            {
                text = "余额兔";
            }
            if (text.Length > 63) text = text.Substring(0, 63);
            tray.Text = text;
        }

        private void CheckLowBalance(Stats value)
        {
            if (settings.LowThreshold <= 0) return;
            if (!value.Balance.HasValue) return;
            if (value.Balance.Value >= settings.LowThreshold) return;
            if ((DateTime.UtcNow - lastLowNotify).TotalHours < 6) return;
            lastLowNotify = DateTime.UtcNow;
            try
            {
                tray.ShowBalloonTip(6000, "余额兔提醒",
                    "余额只剩下 " + Format.Money2(value.Balance.Value) + "，记得充值～",
                    ToolTipIcon.Warning);
            }
            catch
            {
                // 忽略
            }
        }

        private void ApplyRefreshTimer()
        {
            refreshTimer.Stop();
            int minutes = settings.RefreshMinutes;
            if (minutes > 0)
            {
                minutes = Math.Max(1, Math.Min(1440, minutes));
                refreshTimer.Interval = minutes * 60 * 1000;
                refreshTimer.Start();
            }
        }

        // ---------- 气泡 ----------

        private void ToggleBubble()
        {
            if (bubble.Visible)
            {
                HideBubble();
                return;
            }
            ShowBubble();
        }

        private void ShowBubble()
        {
            Rectangle anchor = docked && dock.Visible ? dock.Bounds : pet.Bounds;
            Rectangle work = Screen.FromRectangle(anchor).WorkingArea;
            float scale = LayeredForm.ScaleForRectangle(work);
            int width = (int)Math.Round(BubblePainter.DesignWidth * scale);
            int height = (int)Math.Round(BubblePainter.DesignHeight * scale);

            int x = anchor.Left + anchor.Width / 2 - width / 2;
            int y = anchor.Top - height - (int)Math.Round(4 * scale);
            bool tailUp = false;
            if (y < work.Top + 4)
            {
                y = anchor.Bottom + (int)Math.Round(4 * scale);
                tailUp = true;
            }

            x = Math.Max(work.Left + 4, Math.Min(work.Right - width - 4, x));
            y = Math.Max(work.Top + 4, Math.Min(work.Bottom - height - 4, y));

            float tailDesign = (anchor.Left + anchor.Width / 2f - x) / scale;
            bubble.LowThreshold = settings.LowThreshold;
            bubble.ShowAt(new Point(x, y), tailDesign, tailUp);
            bubble.SetState(stats, refreshing);
            bubble.Render();
            bubbleShownAt = DateTime.UtcNow;
        }

        private void HideBubble()
        {
            if (!bubble.Visible) return;
            bubble.Hide();
        }

        private void OnBubbleTimer(object sender, EventArgs e)
        {
            if (!bubble.Visible) return;
            Point cursor = Cursor.Position;
            if (bubble.Bounds.Contains(cursor))
            {
                bubbleShownAt = DateTime.UtcNow;
                return;
            }
            if ((DateTime.UtcNow - bubbleShownAt).TotalSeconds >= 30) HideBubble();
        }

        // ---------- 宠物拖动 / 缩放 ----------

        private void OnPetDragEnded()
        {
            HideBubble();
            if (settings.EdgeDockEnabled)
            {
                Rectangle area = Screen.FromRectangle(pet.Bounds).WorkingArea;
                int threshold = (int)Math.Round(28 * pet.DpiScale);
                int leftDistance = pet.Left - area.Left;
                int rightDistance = area.Right - pet.Right;
                if (leftDistance <= threshold && leftDistance <= rightDistance)
                {
                    Dock(DockEdge.Left);
                    return;
                }
                if (rightDistance <= threshold)
                {
                    Dock(DockEdge.Right);
                    return;
                }
            }
            ClampPetOnScreen();
            SavePetPosition();
        }

        private void OnPetResizeRequested(float delta)
        {
            int size = (int)Math.Round(pet.LogicalSize + delta);
            size = Math.Max(96, Math.Min(320, size));
            if (size == pet.LogicalSize) return;

            Rectangle old = pet.Bounds;
            pet.SetLogicalSize(size);
            float scale = pet.DpiScale;
            int pixel = (int)Math.Round(size * scale);
            pet.Location = new Point(
                old.Left + old.Width / 2 - pixel / 2,
                old.Bottom - pixel);
            ClampPetOnScreen();
            settings.PetSize = size;
            if (!docked) SavePetPosition();
            if (bubble.Visible) ShowBubble();
        }

        private void ClampPetOnScreen()
        {
            Rectangle work = Screen.FromRectangle(pet.Bounds).WorkingArea;
            int x = Math.Max(work.Left, Math.Min(work.Right - pet.Width, pet.Left));
            int y = Math.Max(work.Top, Math.Min(work.Bottom - pet.Height, pet.Top));
            if (x != pet.Left || y != pet.Top) pet.Location = new Point(x, y);
        }

        private bool IsPetVisibleOnAnyScreen()
        {
            var rect = new Rectangle(pet.Location, pet.Size);
            return Screen.AllScreens.AnyScreenContains(rect) &&
                Screen.FromRectangle(rect).WorkingArea.IntersectsWith(rect);
        }

        /// <summary>所有“把兔子叫回来”的入口都走这里：先恢复显示、取消吸附、再保证在屏幕内。</summary>
        private void ShowPetAnywhere()
        {
            if (docked) Undock();
            settings.PetHidden = false;
            pet.Show();
            if (!IsPetVisibleOnAnyScreen()) ResetPetPosition();
            else ClampPetOnScreen();
            pet.Render();
            SavePetPosition();
        }

        /// <summary>把兔子放回主屏右下角，用于显示器拔插 / 分辨率变化后找不到兔子的情况。</summary>
        private void ResetPetPosition()
        {
            if (docked) Undock();
            settings.PetHidden = false;
            Rectangle work = Screen.PrimaryScreen.WorkingArea;
            float scale = LayeredForm.ScaleForRectangle(work);
            pet.Size = new Size(
                (int)Math.Round(pet.LogicalSize * scale),
                (int)Math.Round(pet.LogicalSize * scale));
            pet.Location = new Point(work.Right - pet.Width - 36, work.Bottom - pet.Height - 24);
            pet.Show();
            pet.Render();
            SavePetPosition();
            if (bubble.Visible) ShowBubble();
        }

        private void HandleDisplayChanged()
        {
            try
            {
                if (docked) Undock();
                else if (pet.Visible)
                {
                    if (!IsPetVisibleOnAnyScreen()) ResetPetPosition();
                    else ClampPetOnScreen();
                }
                if (bubble.Visible) ShowBubble();
            }
            catch
            {
                // 忽略
            }
        }

        private void SavePetPosition()
        {
            settings.PetX = pet.Left;
            settings.PetY = pet.Top;
        }

        // ---------- 边缘吸附 ----------

        private void Dock(DockEdge edge)
        {
            if (docked) return;
            dockWorkArea = Screen.FromRectangle(pet.Bounds).WorkingArea;
            docked = true;
            dockEdge = edge;
            dockAnchor = pet.Top + pet.Height / 2;
            float scale = LayeredForm.ScaleForRectangle(dockWorkArea);
            int half = (int)Math.Round(DockPainter.LogicalSize * scale / 2);
            dockAnchor = Math.Max(dockWorkArea.Top + half,
                Math.Min(dockWorkArea.Bottom - half, dockAnchor));
            dockExpanded = false;
            pet.Hide();
            bubble.Hide();
            dock.SetEdge(edge);
            PositionDock();
            dock.Show();
            dock.Render();
        }

        private void PositionDock()
        {
            if (!docked) return;
            Rectangle area = dockWorkArea;
            float scale = LayeredForm.ScaleForRectangle(area);
            int size = (int)Math.Round(DockPainter.LogicalSize * scale);
            // 先把窗口挪到目标显示器，再按该显示器 DPI 定位置（多屏混合 DPI）
            int roughX = dockEdge == DockEdge.Left ? area.Left : area.Right - size;
            int roughY = dockAnchor - size / 2;
            dock.Location = new Point(roughX, roughY);
            dock.Size = new Size(size, size);

            int hidden = size / 2;
            int peek = dockExpanded ? (int)Math.Round(14 * scale) : 0;
            int x = dockEdge == DockEdge.Left
                ? area.Left - hidden + peek
                : area.Right - size + hidden - peek;
            int y = dockAnchor - size / 2;
            y = Math.Max(area.Top, Math.Min(area.Bottom - size, y));
            dock.Location = new Point(x, y);
        }

        private void OnDockHoverChanged(bool hovering)
        {
            if (!docked) return;
            dockExpanded = hovering;
            PositionDock();
        }

        private void OnDockDragMoved(int deltaY)
        {
            if (!docked) return;
            Rectangle area = dockWorkArea;
            int half = dock.Height / 2;
            dockAnchor += deltaY;
            dockAnchor = Math.Max(area.Top + half, Math.Min(area.Bottom - half, dockAnchor));
            PositionDock();
        }

        private void Undock()
        {
            if (!docked) return;
            Rectangle area = dockWorkArea;
            float scale = LayeredForm.ScaleForRectangle(area);
            int petSize = (int)Math.Round(pet.LogicalSize * scale);
            int margin = (int)Math.Round(8 * scale);
            int x = dockEdge == DockEdge.Left ? area.Left + margin : area.Right - petSize - margin;
            int y = dockAnchor - petSize / 2;
            y = Math.Max(area.Top, Math.Min(area.Bottom - petSize, y));

            dock.Hide();
            docked = false;
            dockExpanded = false;
            pet.Size = new Size(petSize, petSize);
            pet.Location = new Point(x, y);
            pet.Show();
            pet.Render();
            SavePetPosition();
            if (bubble.Visible) ShowBubble();
        }

        // ---------- 菜单 ----------

        private ContextMenuStrip BuildMenu()
        {
            var menu = new ContextMenuStrip();
            menu.Opening += delegate
            {
                menu.Items.Clear();
                PopulateMenu(menu);
            };
            return menu;
        }

        private ToolStripMenuItem Item(string text, Action handler, bool enabled = true)
        {
            var item = new ToolStripMenuItem(text);
            if (handler != null) item.Click += delegate { handler(); };
            item.Enabled = enabled;
            return item;
        }

        private void PopulateMenu(ContextMenuStrip menu)
        {
            string header = stats != null && stats.Balance.HasValue
                ? "余额 " + Format.Money2(stats.Balance.Value)
                : "余额 —";
            menu.Items.Add(Item(header, null, false));

            if (stats != null && !string.IsNullOrEmpty(stats.Error))
            {
                menu.Items.Add(Item("⚠︎ " + stats.Error, null, false));
            }

            if (stats != null && stats.AccountUserId.HasValue)
            {
                menu.Items.Add(Item("账户 #" + stats.AccountUserId.Value, null, false));
            }

            if (stats != null && stats.MultipleAccounts)
            {
                menu.Items.Add(Item("⚠︎ 当前 Key 可见多个账户，已按账户过滤", null, false));
            }

            if (Credentials.HasKey)
            {
                menu.Items.Add(Item("当前 Key 尾号 " + Credentials.KeyHint, null, false));
            }

            if (stats != null && stats.WeekRecharged > 0)
            {
                menu.Items.Add(Item("近 7 天充值 " + Format.Money2(stats.WeekRecharged), null, false));
            }

            if (stats != null && stats.AccountInactive)
            {
                // is_active 语义未知：朋友账号能正常调用也会返回 false，不能当停用告警
                menu.Items.Add(Item("接口状态：is_active = false（如能正常使用可忽略）", null, false));
            }

            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(Item("刷新余额", delegate { Refresh(true); }));
            menu.Items.Add(Item("复制余额", CopyBalance));
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(Item("打开商店 / 充值", delegate
            {
                try
                {
                    System.Diagnostics.Process.Start("https://www.rabbitj.top/shop");
                }
                catch
                {
                    // 忽略
                }
            }));
            menu.Items.Add(new ToolStripSeparator());

            var refreshParent = new ToolStripMenuItem("自动刷新");
            foreach (int minutes in new[] { 0, 5, 10, 30, 60 })
            {
                var item = new ToolStripMenuItem(minutes == 0 ? "关闭定时刷新" : "每 " + minutes + " 分钟");
                item.Checked = settings.RefreshMinutes == minutes;
                int captured = minutes;
                item.Click += delegate
                {
                    settings.RefreshMinutes = captured;
                    ApplyRefreshTimer();
                    Refresh(true);
                };
                refreshParent.DropDownItems.Add(item);
            }
            menu.Items.Add(refreshParent);

            var thresholdParent = new ToolStripMenuItem("低余额提醒");
            foreach (double threshold in new[] { 0d, 10d, 20d, 50d, 100d })
            {
                var item = new ToolStripMenuItem(threshold <= 0
                    ? "关闭提醒"
                    : "低于 ¥" + (int)threshold + " 时提醒");
                item.Checked = Math.Abs(settings.LowThreshold - threshold) < 0.01;
                double captured = threshold;
                item.Click += delegate
                {
                    settings.LowThreshold = captured;
                    pet.LowBalance = captured > 0 && stats != null && stats.IsLow(captured);
                    bubble.LowThreshold = captured;
                    pet.Render();
                    Refresh(true);
                };
                thresholdParent.DropDownItems.Add(item);
            }
            menu.Items.Add(thresholdParent);

            var startup = new ToolStripMenuItem("开机自动启动");
            startup.Checked = Startup.IsEnabled();
            startup.Click += delegate
            {
                if (Startup.IsEnabled()) Startup.Disable();
                else Startup.Enable();
            };
            menu.Items.Add(startup);

            menu.Items.Add(Item("把兔子放回屏幕右下角", ResetPetPosition));

            menu.Items.Add(new ToolStripSeparator());

            var sizeParent = new ToolStripMenuItem("兔子大小");
            var presets = new[]
            {
                new { Title = "小 · 120", Value = 120 },
                new { Title = "中 · 176", Value = 176 },
                new { Title = "大 · 240", Value = 240 },
                new { Title = "特大 · 300", Value = 300 }
            };
            foreach (var preset in presets)
            {
                var item = new ToolStripMenuItem(preset.Title);
                item.Checked = Math.Abs(pet.LogicalSize - preset.Value) < 2;
                int captured = preset.Value;
                item.Click += delegate { ApplyPetSize(captured); };
                sizeParent.DropDownItems.Add(item);
            }
            sizeParent.DropDownItems.Add(new ToolStripSeparator());
            sizeParent.DropDownItems.Add(Item("放大", delegate { ApplyPetSize(pet.LogicalSize + 12); }));
            sizeParent.DropDownItems.Add(Item("缩小", delegate { ApplyPetSize(pet.LogicalSize - 12); }));
            var hint = new ToolStripMenuItem("Ctrl / Alt + 滚轮可自由缩放");
            hint.Enabled = false;
            sizeParent.DropDownItems.Add(hint);
            menu.Items.Add(sizeParent);

            if (docked)
            {
                menu.Items.Add(Item("从边缘弹出", delegate { Undock(); }));
            }

            var dockToggle = new ToolStripMenuItem("拖到屏幕边缘自动吸附");
            dockToggle.Checked = settings.EdgeDockEnabled;
            dockToggle.Click += delegate
            {
                settings.EdgeDockEnabled = !settings.EdgeDockEnabled;
                if (!settings.EdgeDockEnabled && docked) Undock();
            };
            menu.Items.Add(dockToggle);

            menu.Items.Add(Item(settings.PetHidden ? "显示兔子" : "隐藏兔子", delegate
            {
                settings.PetHidden = !settings.PetHidden;
                if (settings.PetHidden)
                {
                    if (docked)
                    {
                        dock.Hide();
                        docked = false;
                        dockExpanded = false;
                    }
                    pet.Hide();
                    dock.Hide();
                    HideBubble();
                }
                else
                {
                    ShowPetAnywhere();
                }
            }));

            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(Item(Credentials.HasKey ? "更换 API Key（换账号）…" : "设置 API Key…",
                delegate { ShowKeyDialog(false); }));
            menu.Items.Add(Item("打开配置文件位置", delegate
            {
                try
                {
                    Directory.CreateDirectory(Settings.DataDirectory);
                    Credentials.Current.Save();
                    System.Diagnostics.Process.Start("explorer.exe", "/select,\"" + Credentials.Current.ConfigPath + "\"");
                }
                catch
                {
                    // 忽略
                }
            }));
            menu.Items.Add(Item("使用说明 / 关于", delegate { ShowAbout(); }));
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(Item("退出余额兔", delegate { Quit(); }));
        }

        private void ShowContextMenu()
        {
            ContextMenuStrip menu = tray.ContextMenuStrip;
            if (menu == null) return;
            // 重新生成内容后再弹出
            menu.Items.Clear();
            PopulateMenu(menu);
            menu.Show(Cursor.Position);
        }

        private void ApplyPetSize(int requested)
        {
            int size = Math.Max(96, Math.Min(320, requested));
            if (size == pet.LogicalSize) return;
            Rectangle old = pet.Bounds;
            float scale = pet.DpiScale;
            pet.SetLogicalSize(size);
            int pixel = (int)Math.Round(size * scale);
            pet.Location = new Point(old.Left + old.Width / 2 - pixel / 2, old.Bottom - pixel);
            ClampPetOnScreen();
            settings.PetSize = size;
            SavePetPosition();
            if (bubble.Visible) ShowBubble();
        }

        private void CopyBalance()
        {
            string text = stats != null && stats.Balance.HasValue
                ? Format.Money2(stats.Balance.Value)
                : "—";
            try
            {
                Clipboard.SetText(text);
            }
            catch
            {
                // 忽略
            }
            ShowBubble();
        }

        private void ShowAbout()
        {
            MessageBox.Show(
                "余额兔 · Windows 版 " + AppVersion() + "\n\n" +
                "桌面兔子 + 余额气泡，常驻托盘。\n" +
                "数据来自 rabbitj.top（anyGPT）的 usage 接口，\n" +
                "API Key 只保存在本机（Windows DPAPI 加密）。\n\n" +
                "操作：\n" +
                "· 左键点兔子：打开 / 收起余额气泡\n" +
                "· 拖动兔子：移动；拖到屏幕左 / 右边缘：吸附\n" +
                "· Ctrl / Alt + 滚轮：缩放兔子\n" +
                "· 右键：菜单（刷新、大小、设置 API Key…）\n" +
                "· 点气泡：刷新余额",
                "关于余额兔",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
        }

        private bool ShowKeyDialog(bool firstRun)
        {
            using (var dialog = new KeyDialog(Credentials.ResolveApiKey()))
            {
                if (dialog.ShowDialog() != DialogResult.OK) return false;
                if (string.IsNullOrEmpty(dialog.ApiKey)) return false;
                Credentials.Current.ApiKey = dialog.ApiKey;
                settings.LastRunVersion = AppVersion();
                if (!firstRun) Refresh(true);
                return true;
            }
        }

        private void OnTrayClick(object sender, MouseEventArgs e)
        {
            if (e.Button != MouseButtons.Left) return;
            trayClickTimer.Stop();
            trayClickTimer.Start();
        }

        private void OnTrayDoubleClick(object sender, MouseEventArgs e)
        {
            if (e.Button != MouseButtons.Left) return;
            trayClickTimer.Stop();
            ShowPetAnywhere();
        }

        private void Quit()
        {
            try
            {
                if (systemEventsHandler != null)
                {
                    Microsoft.Win32.SystemEvents.DisplaySettingsChanged -= systemEventsHandler;
                }
            }
            catch
            {
                // 忽略
            }
            refreshTimer.Stop();
            bubbleTimer.Stop();
            tray.Visible = false;
            tray.Dispose();
            pet.Close();
            bubble.Close();
            dock.Close();
            ExitThread();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                try
                {
                    tray.Dispose();
                }
                catch
                {
                    // 忽略
                }
            }
            base.Dispose(disposing);
        }
    }

    internal static class ScreenExtensions
    {
        public static bool AnyScreenContains(this Screen[] screens, Rectangle rect)
        {
            foreach (Screen screen in screens)
            {
                if (screen.WorkingArea.IntersectsWith(rect)) return true;
            }
            return false;
        }
    }
}
