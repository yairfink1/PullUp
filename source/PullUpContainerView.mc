import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.Timer;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpContainerView - Single viewport container hosting all 3 app pages.
//
// Page 0: Quick Set           (y = 0)
// Page 1: Multi-Set Workout   (y = screenHeight)
// Page 2: 7-Day History       (y = 2 * screenHeight)
//
// Maintains continuous vertical scroll offset _scrollY for real-time
// interactive touch dragging, partial scroll rendering, and smooth snapping.
// ---------------------------------------------------------------------------
class PullUpContainerView extends WatchUi.View {

    // Current and target vertical scroll offset (pixels)
    private var _scrollY       as Number = 0;
    private var _targetScrollY as Number = 0;

    // Quick Set (Page 0) state
    private var _quickIsRecording as Boolean = false;
    private var _quickReps        as Number  = 0;
    private var _quickTimeText    as String  = "00:00";
    private var _quickSampleText  as String  = "Press START";
    private var _quickStatusText  as String  = "PULL UP";

    // Multi-Set (Page 1) state
    private var _multiIsRecording as Boolean = false;
    private var _multiSetNum      as Number  = 1;
    private var _multiSetReps     as Number  = 0;
    private var _multiTotalReps   as Number  = 0;
    private var _multiTimeText    as String  = "00:00";
    private var _multiSampleText  as String  = "";

    // Page indicator auto-hide timer
    private var _lastInteractionTime as Number = 0;
    private var _indicatorTimer      as Timer.Timer?;

    function initialize() {
        View.initialize();
        _lastInteractionTime = System.getTimer();
    }

    function onLayout(dc as Graphics.Dc) as Void {
        // Dynamic procedural rendering in onUpdate
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

    // Scroll offset manipulation
    public function getScrollY() as Number {
        return _scrollY;
    }

    public function setScrollY(newY as Number) as Void {
        _scrollY = newY;
    }

    public function getTargetScrollY() as Number {
        return _targetScrollY;
    }

    public function setTargetScrollY(target as Number) as Void {
        _targetScrollY = target;
    }

    public function getActivePageIndex() as Number {
        var h = System.getDeviceSettings().screenHeight;
        if (h <= 0) { h = 390; }
        var page = (_scrollY + (h / 2)) / h;
        if (page < 0) { page = 0; }
        if (page > 2) { page = 2; }
        return page;
    }

    // --- State setters for Quick Set ---
    public function setQuickRecording(recording as Boolean) as Void {
        _quickIsRecording = recording;
    }
    public function setQuickRepCount(reps as Number) as Void {
        _quickReps = reps;
    }
    public function setQuickElapsedTime(timeStr as String) as Void {
        _quickTimeText = timeStr;
    }
    public function setQuickSampleCount(samples as Number) as Void {
        _quickSampleText = "Samples: " + samples.toString();
    }
    public function setQuickStatus(text as String) as Void {
        _quickStatusText = text;
    }

    // --- State setters for Multi-Set ---
    public function setMultiRecording(recording as Boolean) as Void {
        _multiIsRecording = recording;
    }
    public function setMultiSetNum(setNum as Number) as Void {
        _multiSetNum = setNum;
    }
    public function setMultiSetReps(reps as Number) as Void {
        _multiSetReps = reps;
    }
    public function setMultiTotalReps(total as Number) as Void {
        _multiTotalReps = total;
    }
    public function setMultiElapsedTime(timeStr as String) as Void {
        _multiTimeText = timeStr;
    }
    public function setMultiSampleText(text as String) as Void {
        _multiSampleText = text;
    }

    public function isRecordingAny() as Boolean {
        return _quickIsRecording || _multiIsRecording;
    }

    // --- Main Drawing Pipeline ---
    function onUpdate(dc as Graphics.Dc) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;

        // Clear background (AMOLED black)
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        // Calculate page vertical positions relative to _scrollY
        var y0 = -_scrollY;         // Page 0: Quick Set
        var y1 = y0 + h;            // Page 1: Multi-Set
        var y2 = y0 + (2 * h);      // Page 2: 7-Day History

        // Render visible pages (only if intersecting screen [0, h])
        if (y0 + h > 0 && y0 < h) {
            renderQuickSet(dc, cx, y0);
        }
        if (y1 + h > 0 && y1 < h) {
            renderMultiSet(dc, cx, y1);
        }
        if (y2 + h > 0 && y2 < h) {
            renderHistory(dc, cx, y2);
        }

        // Overlay stationary 3-dot page indicator at 9 o'clock
        if (PageIndicator.isVisible(_lastInteractionTime)) {
            PageIndicator.draw(dc, getActivePageIndex(), 3);
        }
    }

    // --- Page 0: Quick Set ---
    private function renderQuickSet(dc as Graphics.Dc, cx as Number, yOff as Number) as Void {
        var h = dc.getHeight();
        var numFont = (h >= 360) ? Graphics.FONT_NUMBER_THAI_HOT : Graphics.FONT_NUMBER_HOT;

        if (_quickIsRecording) {
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.11).toNumber(), Graphics.FONT_SMALL, _quickStatusText, Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.23).toNumber(), numFont, _quickReps.toString(), Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.57).toNumber(), Graphics.FONT_XTINY, "REPS", Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.65).toNumber(), Graphics.FONT_MEDIUM, _quickTimeText, Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.81).toNumber(), Graphics.FONT_XTINY, _quickSampleText, Graphics.TEXT_JUSTIFY_CENTER);
        } else {
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.11).toNumber(), Graphics.FONT_SMALL, "QUICK SET", Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.23).toNumber(), numFont, "0", Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.57).toNumber(), Graphics.FONT_XTINY, "Press START to record", Graphics.TEXT_JUSTIFY_CENTER);

            var today = PullUpStorage.getTodayReps();
            var prSet = PullUpStorage.getPrSet();
            dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.67).toNumber(), Graphics.FONT_TINY, "Today: " + today + " reps", Graphics.TEXT_JUSTIFY_CENTER);

            if (prSet > 0) {
                dc.setColor(Graphics.COLOR_YELLOW, Graphics.COLOR_TRANSPARENT);
                dc.drawText(cx, yOff + (h * 0.77).toNumber(), Graphics.FONT_XTINY, "PR Set: " + prSet + " reps", Graphics.TEXT_JUSTIFY_CENTER);
            }

            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.86).toNumber(), Graphics.FONT_XTINY, "DOWN = Multi-Set Workout", Graphics.TEXT_JUSTIFY_CENTER);
        }
    }

    // --- Page 1: Multi-Set Workout ---
    private function renderMultiSet(dc as Graphics.Dc, cx as Number, yOff as Number) as Void {
        var h = dc.getHeight();
        var numFont = (h >= 360) ? Graphics.FONT_NUMBER_THAI_HOT : Graphics.FONT_NUMBER_HOT;

        if (_multiIsRecording) {
            dc.setColor(Graphics.COLOR_ORANGE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.09).toNumber(), Graphics.FONT_SMALL, "SET " + _multiSetNum, Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.22).toNumber(), numFont, _multiSetReps.toString(), Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.55).toNumber(), Graphics.FONT_XTINY, "REPS", Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.62).toNumber(), Graphics.FONT_MEDIUM, _multiTimeText, Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.78).toNumber(), Graphics.FONT_XTINY, "Total: " + _multiTotalReps + " | " + _multiSampleText, Graphics.TEXT_JUSTIFY_CENTER);
        } else {
            dc.setColor(Graphics.COLOR_ORANGE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.09).toNumber(), Graphics.FONT_SMALL, "MULTI-SET", Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.22).toNumber(), numFont, _multiSetNum.toString(), Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.55).toNumber(), Graphics.FONT_XTINY, "Ready for Set " + _multiSetNum, Graphics.TEXT_JUSTIFY_CENTER);

            var today = PullUpStorage.getTodayReps();
            dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.67).toNumber(), Graphics.FONT_TINY, "Today: " + today + " reps", Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.86).toNumber(), Graphics.FONT_XTINY, "DOWN = 7-Day History", Graphics.TEXT_JUSTIFY_CENTER);
        }
    }

    // --- Page 2: 7-Day History (Native Steps Style) ---
    private function renderHistory(dc as Graphics.Dc, cx as Number, yOff as Number) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
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

        var avgReps = (numDays > 0) ? ((weekTotal + 3) / numDays) : 0;
        var prDay = PullUpStorage.getPrDay();
        var prSet = PullUpStorage.getPrSet();

        // Title & Average
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, yOff + (h * 0.07).toNumber(), Graphics.FONT_XTINY, "Pull-Ups", Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, yOff + (h * 0.12).toNumber(), Graphics.FONT_LARGE, avgReps + " Avg.", Graphics.TEXT_JUSTIFY_CENTER);

        // Scale & Grid Lines
        var scaleMax = maxReps;
        if (scaleMax < 50) {
            scaleMax = 50;
        }

        var chartTop    = yOff + (h * 0.29).toNumber();
        var chartBottom = yOff + (h * 0.59).toNumber();
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

        // 7 Bars
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

            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(barX + (barWidth / 2), chartBottom + 4, Graphics.FONT_XTINY, letter, Graphics.TEXT_JUSTIFY_CENTER);
        }

        // Solid X-Axis Baseline
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(chartLeft - 4, chartBottom, chartRight + 4, chartBottom);

        // All-time PR badge banner
        if (prSet > 0 || prDay > 0) {
            dc.setColor(Graphics.COLOR_YELLOW, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, yOff + (h * 0.74).toNumber(), Graphics.FONT_XTINY, "PRs: Set " + prSet + " | Day " + prDay, Graphics.TEXT_JUSTIFY_CENTER);
        }

        // Navigation Hint
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, yOff + (h * 0.86).toNumber(), Graphics.FONT_XTINY, "UP = Multi-Set", Graphics.TEXT_JUSTIFY_CENTER);
    }
}
