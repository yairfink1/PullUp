import Toybox.Lang;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpCelebrationDelegate - handles early dismissal of celebration view.
// ---------------------------------------------------------------------------
class PullUpCelebrationDelegate extends WatchUi.BehaviorDelegate {

    private var _view as PullUpCelebrationView;

    function initialize(view as PullUpCelebrationView) {
        BehaviorDelegate.initialize();
        _view = view;
    }

    function onKey(keyEvent as WatchUi.KeyEvent) as Boolean {
        _view.onAutoDismiss();
        return true;
    }

    function onSelect() as Boolean {
        _view.onAutoDismiss();
        return true;
    }

    function onBack() as Boolean {
        _view.onAutoDismiss();
        return true;
    }

    function onPreviousPage() as Boolean {
        _view.onAutoDismiss();
        return true;
    }

    function onNextPage() as Boolean {
        _view.onAutoDismiss();
        return true;
    }
}
