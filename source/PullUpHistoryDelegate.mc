import Toybox.Lang;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpHistoryDelegate - input handling for Page 3 (7-Day History Screen).
//
// Handles navigation:
//   - UP / onPreviousPage(): Return to Page 2 (PullUpMultiSetView) with SLIDE_DOWN.
//   - BACK / onBack(): Standard back behavior.
// ---------------------------------------------------------------------------
class PullUpHistoryDelegate extends WatchUi.BehaviorDelegate {

    private var _view as PullUpHistoryView;

    function initialize(view as PullUpHistoryView) {
        BehaviorDelegate.initialize();
        _view = view;
    }

    function onKey(keyEvent as WatchUi.KeyEvent) as Boolean {
        return BehaviorDelegate.onKey(keyEvent);
    }

    function onBack() as Boolean {
        return false; // Default system back handling
    }
}
