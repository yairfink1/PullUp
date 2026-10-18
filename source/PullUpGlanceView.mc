import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpGlanceView - displays today's and weekly repetitions in the glance list.
//
// Annotated with (:glance) for strict memory efficiency.
// ---------------------------------------------------------------------------
(:glance)
class PullUpGlanceView extends WatchUi.GlanceView {

    function initialize() {
        GlanceView.initialize();
    }

    function onLayout(dc as Graphics.Dc) as Void {
        // Dynamic layout drawn in onUpdate.
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var h = dc.getHeight();
        var todayReps = PullUpStorage.getTodayReps();
        var weekReps  = PullUpStorage.getWeekReps();

        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        var titleFont  = (Graphics has :FONT_GLANCE) ? Graphics.FONT_GLANCE : Graphics.FONT_TINY;
        var metricFont = (Graphics has :FONT_XTINY)  ? Graphics.FONT_XTINY  : titleFont;

        // 1. App Title
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(0, (h * 0.05).toNumber(), titleFont, "Pull Ups", Graphics.TEXT_JUSTIFY_LEFT);

        // 2. Line 1: Today's reps
        var todayColor = (todayReps > 0) ? Graphics.COLOR_GREEN : Graphics.COLOR_LT_GRAY;
        dc.setColor(todayColor, Graphics.COLOR_TRANSPARENT);
        var todayText = todayReps.toString() + ((todayReps == 1) ? " rep today" : " reps today");
        dc.drawText(0, (h * 0.38).toNumber(), metricFont, todayText, Graphics.TEXT_JUSTIFY_LEFT);

        // 3. Line 2: Weekly reps
        var weekColor = (weekReps > 0) ? Graphics.COLOR_LT_GRAY : Graphics.COLOR_DK_GRAY;
        dc.setColor(weekColor, Graphics.COLOR_TRANSPARENT);
        var weekText = weekReps.toString() + ((weekReps == 1) ? " rep this week" : " reps this week");
        dc.drawText(0, (h * 0.68).toNumber(), metricFont, weekText, Graphics.TEXT_JUSTIFY_LEFT);
    }
}
