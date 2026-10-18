import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.Timer;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpHistoryView - Page 3: 7-Day rolling history (Native Garmin Steps style).
//
// Native Garmin widget design matching garmin_steps.png:
//   - Header: "Pull-Ups" title + "X Avg." primary stat (7-day daily average).
//   - 2 faint horizontal grid guidelines with scale labels on the right edge.
//   - Clean 11px bars (NO floating numbers above bars).
//   - Goal threshold logic: Green ONLY if daily reps >= 100, otherwise steel-blue.
//   - Tiny 2px base dash for 0-rep days.
//   - Solid horizontal baseline separating chart from day letter labels.
//   - Auto-hiding 3-dot page indicator on left bezel.
// ---------------------------------------------------------------------------
class PullUpHistoryView extends WatchUi.View {

    private var _lastInteractionTime as Number = 0;
    private var _indicatorTimer      as Timer.Timer?;

    function initialize() {
        View.initialize();
        _lastInteractionTime = System.getTimer();
    }

    function onLayout(dc as Graphics.Dc) as Void {
        // Drawn dynamically in onUpdate.
    }

    function onShow() as Void {
        resetIndicatorTimer();
        WatchUi.requestUpdate();
    }

    function onHide() as Void {
        if (_indicatorTimer != null) {
            _indicatorTimer.stop();
            _indicatorTimer = null;
        }
    }

    public function resetIndicatorTimer() as Void {
        _lastInteractionTime = System.getTimer();
        if (_indicatorTimer == null) {
            _indicatorTimer = new Timer.Timer();
        }
        _indicatorTimer.stop();
        _indicatorTimer.start(method(:onIndicatorTimeout), PageIndicator.TIMEOUT_MS, false);
    }

    public function onIndicatorTimeout() as Void {
        WatchUi.requestUpdate();
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var w  = dc.getWidth();
        var h  = dc.getHeight();
        var cx = w / 2;

        // Clear background (AMOLED black)
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        // 1. Fetch 7-day rolling history
        var daysData  = PullUpStorage.getRolling7Days();
        var weekTotal = 0;
        var maxReps   = 0;
        var numDays   = daysData.size();

        for (var i = 0; i < numDays; i++) {
            var r = daysData[i][:reps] as Number;
            weekTotal += r;
            if (r > maxReps) {
                maxReps = r;
            }
        }

        // Calculate 7-day daily average
        var avgReps = (numDays > 0) ? ((weekTotal + 3) / numDays) : 0;
        var prDay = PullUpStorage.getPrDay();
        var prSet = PullUpStorage.getPrSet();

        // 2. Header Area (Native Steps style)
        // Top label: "Pull-Ups"
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.07).toNumber(), Graphics.FONT_XTINY, "Pull-Ups", Graphics.TEXT_JUSTIFY_CENTER);

        // Primary Stat: "X Avg."
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.12).toNumber(), Graphics.FONT_LARGE, avgReps + " Avg.", Graphics.TEXT_JUSTIFY_CENTER);

        // 3. Scale Ceiling & Grid Lines
        var scaleMax = maxReps;
        if (scaleMax < 50) {
            scaleMax = 50;
        }

        var chartTop    = (h * 0.29).toNumber();
        var chartBottom = (h * 0.59).toNumber();
        var chartHeight = chartBottom - chartTop;

        var chartWidth = (w * 0.54).toNumber();
        var chartLeft  = cx - (chartWidth / 2);
        var chartRight = chartLeft + chartWidth;

        // Top guideline (100% scale)
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(chartLeft, chartTop, chartRight, chartTop);
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(chartRight + 4, chartTop - 7, Graphics.FONT_XTINY, scaleMax.toString(), Graphics.TEXT_JUSTIFY_LEFT);

        // Mid guideline (50% scale)
        var yMid   = chartTop + (chartHeight / 2);
        var midVal = scaleMax / 2;
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(chartLeft, yMid, chartRight, yMid);
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(chartRight + 4, yMid - 7, Graphics.FONT_XTINY, midVal.toString(), Graphics.TEXT_JUSTIFY_LEFT);

        // 4. Bar Geometry & Rendering
        var barWidth      = (w >= 360) ? 11 : 8;
        var totalBarWidth = numDays * barWidth;
        var spacing       = (chartWidth - totalBarWidth) / (numDays - 1);

        for (var i = 0; i < numDays; i++) {
            var dayObj = daysData[i];
            var reps   = dayObj[:reps] as Number;
            var letter = dayObj[:dayLetter] as String;
            var barX   = chartLeft + i * (barWidth + spacing);

            if (reps == 0) {
                var dashH = 2;
                var dashY = chartBottom - dashH;
                dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
                dc.fillRectangle(barX, dashY, barWidth, dashH);
            } else {
                var barH = (reps * chartHeight) / scaleMax;
                if (barH < 3) { barH = 3; }
                if (barH > chartHeight) { barH = chartHeight; }
                var barY = chartBottom - barH;

                if (reps >= 100) {
                    dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
                } else {
                    dc.setColor(Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
                }

                dc.fillRoundedRectangle(barX, barY, barWidth, barH, 2);

                // If this day matches all-time Day PR, highlight with gold dot above bar
                if (prDay > 0 && reps == prDay) {
                    dc.setColor(Graphics.COLOR_YELLOW, Graphics.COLOR_TRANSPARENT);
                    dc.fillCircle(barX + (barWidth / 2), barY - 4, 2);
                }
            }

            // Day initial label below baseline
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(barX + (barWidth / 2), chartBottom + 4, Graphics.FONT_XTINY, letter, Graphics.TEXT_JUSTIFY_CENTER);
        }

        // 5. Solid X-Axis Baseline
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(chartLeft - 4, chartBottom, chartRight + 4, chartBottom);

        // 6. All-time PR badge banner
        if (prSet > 0 || prDay > 0) {
            dc.setColor(Graphics.COLOR_YELLOW, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.74).toNumber(), Graphics.FONT_XTINY, "PRs: Set " + prSet + " | Day " + prDay, Graphics.TEXT_JUSTIFY_CENTER);
        }

        // 7. Bottom Navigation Hint
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.86).toNumber(), Graphics.FONT_XTINY, "UP = Multi-Set", Graphics.TEXT_JUSTIFY_CENTER);

        // 8. 3-Dot Page Indicator (Page 3 of 3)
        if (PageIndicator.isVisible(_lastInteractionTime)) {
            PageIndicator.draw(dc, 2, 3);
        }
    }
}
