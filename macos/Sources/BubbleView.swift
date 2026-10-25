import Cocoa

final class BubbleView: NSView {
    static let size = NSSize(width: 300, height: 282)

    var stats: Stats? { didSet { needsDisplay = true } }
    var isLoading = false { didSet { needsDisplay = true } }
    var tailX: CGFloat = 150 { didSet { needsDisplay = true } }
    /// true = 气泡在宠物下方，尾巴朝上
    var tailUp = false { didSet { needsDisplay = true } }

    /// 鼠标悬停的柱子（0…6）
    var hoverDay: Int? { didSet { needsDisplay = true } }
    /// 点击选中的柱子（0…6），再点一次取消
    var selectedDay: Int? { didSet { needsDisplay = true } }

    var onRefresh: (() -> Void)?
    var onClose: (() -> Void)?
    var onInteraction: (() -> Void)?

    private let cardColor = NSColor(calibratedRed: 0.995, green: 0.988, blue: 0.976, alpha: 1)
    private let accent = NSColor(calibratedRed: 0.353, green: 0.341, blue: 0.839, alpha: 1)

    override var isFlipped: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    // MARK: - 几何（设计画布 300×282，单位 pt）

    private var cardRect: NSRect {
        NSRect(x: 2, y: tailUp ? 20 : 2, width: 296, height: 256)
    }

    private struct ChartGeometry {
        let left: CGFloat = 24
        let width: CGFloat = 250
        let chartTop: CGFloat
        let baseline: CGFloat
        let barWidth: CGFloat = 18
        let barMaxHeight: CGFloat = 28
        let slot: CGFloat
        let hitRect: NSRect

        init(cardTop: CGFloat) {
            chartTop = cardTop + 102
            baseline = chartTop + 40
            slot = width / 7
            hitRect = NSRect(x: left, y: chartTop - 4, width: width, height: 56)
        }
    }

    private var chart: ChartGeometry { ChartGeometry(cardTop: cardRect.minY) }

    // MARK: - 绘制

    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        context.setShouldAntialias(true)
        drawCard()

        if isLoading && stats?.balance == nil {
            drawLoading()
        } else if let value = stats {
            drawContent(value)
        } else {
            drawEmpty()
        }
    }

    // MARK: 卡片

    private func drawCard() {
        let rect = cardRect
        let card = NSBezierPath(roundedRect: rect, xRadius: 18, yRadius: 18)
        let tail = NSBezierPath()
        let tailHalfWidth: CGFloat = 12
        let tailLength: CGFloat = 15
        if tailUp {
            tail.move(to: NSPoint(x: tailX - tailHalfWidth, y: rect.minY + 2))
            tail.line(to: NSPoint(x: tailX + tailHalfWidth, y: rect.minY + 2))
            tail.line(to: NSPoint(x: tailX, y: rect.minY - tailLength))
        } else {
            tail.move(to: NSPoint(x: tailX - tailHalfWidth, y: rect.maxY - 2))
            tail.line(to: NSPoint(x: tailX + tailHalfWidth, y: rect.maxY - 2))
            tail.line(to: NSPoint(x: tailX, y: rect.maxY + tailLength))
        }
        tail.close()

        NSGraphicsContext.saveGraphicsState()
        let shadow = NSShadow()
        shadow.shadowColor = NSColor.black.withAlphaComponent(0.22)
        shadow.shadowBlurRadius = 18
        shadow.shadowOffset = NSSize(width: 0, height: tailUp ? 4 : -4)
        shadow.set()
        cardColor.setFill()
        card.fill()
        tail.fill()
        NSGraphicsContext.restoreGraphicsState()

        NSColor.black.withAlphaComponent(0.06).setStroke()
        let border = NSBezierPath(roundedRect: rect.insetBy(dx: 0.5, dy: 0.5), xRadius: 18, yRadius: 18)
        border.lineWidth = 1
        border.stroke()
    }

    // MARK: 正常内容

    private func drawContent(_ value: Stats) {
        let top = cardRect.minY
        let left: CGFloat = 24
        let right: CGFloat = 274
        let contentWidth = right - left

        let captionFont = NSFont.systemFont(ofSize: 11, weight: .medium)
        let caption = "当前余额"
        let captionSize = measure(caption, font: captionFont)
        text(caption,
             NSRect(x: left, y: top + 18, width: ceil(captionSize.width) + 2, height: 15),
             font: captionFont,
             color: NSColor(calibratedWhite: 0.40, alpha: 1))

        let timeFont = fitFont("\(timeText(value.updatedAt)) 更新",
                               base: NSFont.systemFont(ofSize: 10),
                               maxWidth: contentWidth - captionSize.width - 14,
                               minSize: 8)
        text("\(timeText(value.updatedAt)) 更新",
             NSRect(x: right - 150, y: top + 19, width: 150, height: 14),
             font: timeFont,
             color: NSColor(calibratedWhite: 0.60, alpha: 1),
             align: .right)

        let low = value.isLow && Settings.shared.lowThreshold > 0
        let balanceText = value.balance.map { String(format: "¥%.2f", $0) } ?? "—"
        let balanceFont = fitFont(balanceText,
                                  base: .monospacedDigitSystemFont(ofSize: 31, weight: .semibold),
                                  maxWidth: contentWidth,
                                  minSize: 18)
        text(balanceText,
             NSRect(x: left - 2, y: top + 33, width: contentWidth + 2, height: 42),
             font: balanceFont,
             color: low ? NSColor(calibratedRed: 0.90, green: 0.22, blue: 0.19, alpha: 1) : NSColor(calibratedWhite: 0.12, alpha: 1))

        let overview = "今日 \(moneySmart(value.todaySpend))     近7天 \(moneySmart(value.weekSpend))"
        let overviewFont = fitFont(overview,
                                   base: NSFont.systemFont(ofSize: 12),
                                   maxWidth: contentWidth,
                                   minSize: 9)
        text(overview,
             NSRect(x: left, y: top + 80, width: contentWidth, height: 16),
             font: overviewFont,
             color: NSColor(calibratedWhite: 0.40, alpha: 1))

        drawChart(value)

        NSColor.black.withAlphaComponent(0.07).setFill()
        NSRect(x: left, y: top + 174, width: contentWidth, height: 1).fill()

        let tokenLine = "Tokens \(tokensText(value.weekTokens))   ·   近7天 \(value.weekRequests) 次请求"
        text(tokenLine,
             NSRect(x: left, y: top + 184, width: contentWidth, height: 15),
             font: fitFont(tokenLine, base: .systemFont(ofSize: 11), maxWidth: contentWidth, minSize: 8),
             color: NSColor(calibratedWhite: 0.40, alpha: 1))

        let modelLine: String
        let modelColor: NSColor
        if let first = value.topModels.first {
            modelLine = "近期主力模型 \(first.name)（\(first.count) 次）"
            modelColor = NSColor(calibratedWhite: 0.40, alpha: 1)
        } else {
            modelLine = "近 7 天暂无模型使用记录"
            modelColor = NSColor(calibratedWhite: 0.60, alpha: 1)
        }
        text(modelLine,
             NSRect(x: left, y: top + 203, width: contentWidth, height: 15),
             font: fitFont(modelLine, base: .systemFont(ofSize: 11), maxWidth: contentWidth, minSize: 8),
             color: modelColor)

        if low {
            let lowLine = "余额低于提醒阈值 \(money2(Settings.shared.lowThreshold))，右键可打开充值"
            text(lowLine,
                 NSRect(x: left, y: top + 222, width: contentWidth, height: 15),
                 font: fitFont(lowLine,
                               base: .systemFont(ofSize: 10.5, weight: .medium),
                               maxWidth: contentWidth,
                               minSize: 8),
                 color: NSColor(calibratedRed: 0.90, green: 0.22, blue: 0.19, alpha: 1))
        } else if value.multipleAccounts {
            let multiLine = "当前 Key 可见多个账户，已按账户 #\(value.accountUserId.map(String.init) ?? "?") 过滤"
            text(multiLine,
                 NSRect(x: left, y: top + 222, width: contentWidth, height: 15),
                 font: fitFont(multiLine,
                               base: .systemFont(ofSize: 10, weight: .medium),
                               maxWidth: contentWidth,
                               minSize: 8),
                 color: NSColor(calibratedRed: 0.85, green: 0.50, blue: 0.05, alpha: 1))
        }

        drawFooter(value)
    }

    private func drawFooter(_ value: Stats) {
        let top = cardRect.minY
        let left: CGFloat = 24
        let right: CGFloat = 274
        let contentWidth = right - left
        let footerFont = NSFont.systemFont(ofSize: 9.5)
        let hint = "左键刷新 · 右键更多"
        let hintWidth = ceil(measure(hint, font: footerFont).width) + 2

        // 悬停/选中某一天时，底部显示当天花费与请求数
        if let index = selectedDay ?? hoverDay, index >= 0, index < value.daily.count {
            let day = value.daily[index]
            let detail = "\(shortDate(day.date)) 花费 \(moneySmart(day.spend)) · \(day.requests) 次"
            let available = contentWidth - hintWidth - 10
            text(detail,
                 NSRect(x: left, y: top + 240, width: available, height: 13),
                 font: fitFont(detail, base: footerFont, maxWidth: available, minSize: 8),
                 color: accent)
        } else if let error = value.error {
            let line = "⚠ 刷新失败：\(error)"
            text(line,
                 NSRect(x: left, y: top + 240, width: contentWidth - hintWidth - 10, height: 12),
                 font: fitFont(line, base: footerFont, maxWidth: contentWidth - hintWidth - 10, minSize: 8),
                 color: NSColor(calibratedRed: 0.90, green: 0.22, blue: 0.19, alpha: 1))
        } else if value.partial {
            let line = "记录过多，近 7 天统计已截断"
            text(line,
                 NSRect(x: left, y: top + 240, width: contentWidth - hintWidth - 10, height: 12),
                 font: fitFont(line, base: footerFont, maxWidth: contentWidth - hintWidth - 10, minSize: 8),
                 color: NSColor(calibratedRed: 0.85, green: 0.50, blue: 0.05, alpha: 1))
        } else if let total = value.totalRequests {
            let line = "累计 \(total) 次请求"
            text(line,
                 NSRect(x: left, y: top + 240, width: contentWidth - hintWidth - 10, height: 12),
                 font: footerFont,
                 color: NSColor(calibratedWhite: 0.60, alpha: 1))
        } else if let userId = value.accountUserId {
            let line = "账户 #\(userId)"
            text(line,
                 NSRect(x: left, y: top + 240, width: contentWidth - hintWidth - 10, height: 12),
                 font: footerFont,
                 color: NSColor(calibratedWhite: 0.60, alpha: 1))
        }

        text(hint,
             NSRect(x: right - hintWidth - 2, y: top + 240, width: hintWidth + 2, height: 12),
             font: footerFont,
             color: NSColor(calibratedWhite: 0.60, alpha: 1),
             align: .right)
    }

    private func drawChart(_ value: Stats) {
        let daily = value.daily
        guard daily.count == 7 else { return }
        let geometry = chart
        let todayIndex = daily.count - 1
        let peak = daily.map { $0.spend }.max() ?? 0
        let maxSpend = max(peak, 0.0001)

        for (index, day) in daily.enumerated() {
            let height: CGFloat = day.spend <= 0
                ? 2
                : max(3, geometry.barMaxHeight * CGFloat(day.spend / maxSpend))
            let x = geometry.left + geometry.slot * CGFloat(index) + (geometry.slot - geometry.barWidth) / 2
            let bar = NSBezierPath(roundedRect: NSRect(x: x,
                                                       y: geometry.baseline - height,
                                                       width: geometry.barWidth,
                                                       height: height),
                                   xRadius: 4,
                                   yRadius: 4)
            let highlighted = index == hoverDay || index == selectedDay
            if day.spend <= 0 {
                NSColor.black.withAlphaComponent(0.10).setFill()
            } else if highlighted {
                accent.setFill()
            } else if index == todayIndex {
                accent.withAlphaComponent(0.75).setFill()
            } else {
                NSColor(calibratedRed: 0.749, green: 0.749, blue: 0.788, alpha: 1).setFill()
            }
            bar.fill()

            let labelColor: NSColor
            if highlighted {
                labelColor = NSColor(calibratedWhite: 0.25, alpha: 1)
            } else if index == todayIndex {
                labelColor = NSColor(calibratedWhite: 0.40, alpha: 1)
            } else {
                labelColor = NSColor(calibratedWhite: 0.62, alpha: 1)
            }
            text(shortDate(day.date),
                 NSRect(x: x - 8, y: geometry.baseline + 4, width: geometry.barWidth + 16, height: 12),
                 font: .systemFont(ofSize: 9),
                 color: labelColor,
                 align: .center)
        }

        // 峰值标签：实测宽度，居中在最高柱上方，并限制在卡片内
        guard peak > 0,
              let peakIndex = daily.firstIndex(where: { $0.spend == peak }) else { return }
        let peakText = "峰值 \(moneySmart(peak))"
        let peakFont = NSFont.systemFont(ofSize: 9)
        let measured = measure(peakText, font: peakFont)
        let width = min(geometry.width, ceil(measured.width) + 2)
        let height = min(16, max(12, ceil(measured.height) + 1))
        let center = geometry.left + geometry.slot * CGFloat(peakIndex) + geometry.slot / 2
        let maxX = geometry.left + geometry.width - width
        let x = min(max(geometry.left, center - width / 2), maxX)
        let barTop = geometry.baseline - geometry.barMaxHeight
        let y = max(cardRect.minY + 96, barTop - height - 2)
        text(peakText,
             NSRect(x: x, y: y, width: width, height: height),
             font: peakFont,
             color: NSColor(calibratedWhite: 0.60, alpha: 1),
             align: .right)
    }

    // MARK: 其他状态

    private func drawLoading() {
        let top = cardRect.minY
        text("查询中…",
             NSRect(x: 24, y: top + 34, width: 250, height: 40),
             font: .systemFont(ofSize: 26, weight: .semibold),
             color: NSColor(calibratedWhite: 0.60, alpha: 1))
        text("正在读取最近 7 天的用量记录…",
             NSRect(x: 24, y: top + 82, width: 250, height: 16),
             font: .systemFont(ofSize: 12),
             color: NSColor(calibratedWhite: 0.40, alpha: 1))
    }

    private func drawEmpty() {
        let top = cardRect.minY
        text("点我查余额",
             NSRect(x: 24, y: top + 40, width: 250, height: 36),
             font: .systemFont(ofSize: 22, weight: .semibold),
             color: NSColor(calibratedWhite: 0.12, alpha: 1))
        text("读取 rabbitj.top 账户余额与用量",
             NSRect(x: 24, y: top + 84, width: 250, height: 16),
             font: .systemFont(ofSize: 12),
             color: NSColor(calibratedWhite: 0.40, alpha: 1))
    }

    // MARK: - 交互

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        for area in trackingAreas { removeTrackingArea(area) }
        addTrackingArea(NSTrackingArea(rect: bounds,
                                       options: [.mouseEnteredAndExited, .mouseMoved, .activeAlways, .inVisibleRect],
                                       owner: self,
                                       userInfo: nil))
    }

    override func hitTest(_ point: NSPoint) -> NSView? {
        // 整个气泡窗口（卡片 + 尖角）都算命中，避免点击落到背后窗口
        bounds.contains(point) ? self : nil
    }

    private func dayIndex(at point: NSPoint) -> Int? {
        let geometry = chart
        guard geometry.hitRect.contains(point) else { return nil }
        let index = Int((point.x - geometry.left) / geometry.slot)
        return min(max(index, 0), 6)
    }

    override func mouseMoved(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        let index = dayIndex(at: point)
        if index != hoverDay { hoverDay = index }
        if index != nil {
            NSCursor.pointingHand.set()
        } else {
            NSCursor.arrow.set()
        }
        onInteraction?()
    }

    override func mouseExited(with event: NSEvent) {
        if hoverDay != nil { hoverDay = nil }
        NSCursor.arrow.set()
    }

    override func mouseDown(with event: NSEvent) {
        onInteraction?()
        let point = convert(event.locationInWindow, from: nil)
        if let index = dayIndex(at: point) {
            selectedDay = selectedDay == index ? nil : index
            return
        }
        if cardRect.contains(point) {
            onRefresh?()
        } else {
            onClose?()
        }
    }

    // MARK: - 文本

    private func measure(_ string: String, font: NSFont) -> NSSize {
        (string as NSString).size(withAttributes: [.font: font])
    }

    /// 文字放不下时逐级缩小字号（9pt 起步），保证不压字、不截断
    private func fitFont(_ string: String,
                         base: NSFont,
                         maxWidth: CGFloat,
                         minSize: CGFloat = 8) -> NSFont {
        guard maxWidth > 0 else { return base }
        var size = base.pointSize
        var font = base
        while size > minSize {
            let width = measure(string, font: font).width
            if width <= maxWidth { return font }
            size -= 0.5
            font = NSFont(descriptor: base.fontDescriptor, size: size) ?? NSFont.systemFont(ofSize: size)
        }
        return font
    }

    private func text(_ string: String,
                      _ rect: NSRect,
                      font: NSFont,
                      color: NSColor,
                      align: NSTextAlignment = .left,
                      wrap: Bool = false) {
        let paragraph = NSMutableParagraphStyle()
        paragraph.alignment = align
        paragraph.lineBreakMode = wrap ? .byWordWrapping : .byTruncatingTail
        let attributes: [NSAttributedString.Key: Any] = [
            .font: font,
            .foregroundColor: color,
            .paragraphStyle: paragraph
        ]
        (string as NSString).draw(in: rect, withAttributes: attributes)
    }
}
