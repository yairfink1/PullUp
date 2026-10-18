import Toybox.Attention;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Timer;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpCelebrationView - celebratory screen shown when a new PR is set.
//
// Automatically pops itself after 3.5 seconds, or immediately when any
// physical key or screen tap is received via PullUpCelebrationDelegate.
// ---------------------------------------------------------------------------
class PullUpCelebrationView extends WatchUi.View {

    private var _prTitle       as String;
    private var _prValue       as Number;
    private var _prSub         as String;
    private var _dismissTimer  as Timer.Timer?;
    private var _dismissed     as Boolean = false;

    function initialize(prTitle as String, prValue as Number, prSub as String) {
        View.initialize();
        _prTitle = prTitle;
        _prValue = prValue;
        _prSub   = prSub;
    }

    function onLayout(dc as Graphics.Dc) as Void {
        // Layout calculated proportionally in onUpdate for multi-screen compatibility.
    }

    function onShow() as Void {
        _dismissed = false;

        // Celebratory haptic pulse.
        if (Attention has :vibrate) {
            var vibeData = [
                new Attention.VibeProfile(60, 150),
                new Attention.VibeProfile(0, 100),
                new Attention.VibeProfile(100, 250),
                new Attention.VibeProfile(0, 100),
                new Attention.VibeProfile(100, 350)
            ];
            Attention.vibrate(vibeData);
        }

        // Auto-dismiss after 3.5 seconds.
        if (_dismissTimer == null) {
            _dismissTimer = new Timer.Timer();
        }
        _dismissTimer.start(method(:onAutoDismiss), 3500, false);
    }

    function onHide() as Void {
        if (_dismissTimer != null) {
            _dismissTimer.stop();
            _dismissTimer = null;
        }
        _dismissed = true;
    }

    public function onAutoDismiss() as Void {
        if (!_dismissed) {
            _dismissed = true;
            WatchUi.popView(WatchUi.SLIDE_DOWN);
        }
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var w  = dc.getWidth();
        var h  = dc.getHeight();
        var cx = w / 2;

        // Background
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        // 1. Trophy Banner / Top Header
        dc.setColor(Graphics.COLOR_YELLOW, Graphics.COLOR_TRANSPARENT);
        var headerY = (h * 0.12).toNumber();
        dc.drawText(cx, headerY, Graphics.FONT_TINY, "[ NEW RECORD! ]", Graphics.TEXT_JUSTIFY_CENTER);

        // 2. PR Category ("BEST SET!", "BEST DAY!", "BEST WEEK!")
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        var titleY = (h * 0.23).toNumber();
        dc.drawText(cx, titleY, Graphics.FONT_MEDIUM, _prTitle, Graphics.TEXT_JUSTIFY_CENTER);

        // 3. Highlighted Value (Number)
        dc.setColor(Graphics.COLOR_YELLOW, Graphics.COLOR_TRANSPARENT);
        var numberY = (h * 0.35).toNumber();
        var numFont = (h >= 360) ? Graphics.FONT_NUMBER_THAI_HOT : Graphics.FONT_NUMBER_HOT;
        dc.drawText(cx, numberY, numFont, _prValue.toString(), Graphics.TEXT_JUSTIFY_CENTER);

        // 4. Subtitle / Unit
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        var subY = (h * 0.70).toNumber();
        dc.drawText(cx, subY, Graphics.FONT_SMALL, _prSub, Graphics.TEXT_JUSTIFY_CENTER);

        // 5. Dismiss Hint
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        var hintY = (h * 0.85).toNumber();
        dc.drawText(cx, hintY, Graphics.FONT_XTINY, "Press any key to dismiss", Graphics.TEXT_JUSTIFY_CENTER);
    }
}
