import Toybox.Attention;
import Toybox.FitContributor;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Sensor;
import Toybox.System;
import Toybox.Timer;
import Toybox.WatchUi;
import Toybox.ActivityRecording;
import Toybox.Activity;
import Toybox.SensorLogging;

// ---------------------------------------------------------------------------
// PullUpContainerDelegate - handles input, dragging, snap animation, and workouts.
// ---------------------------------------------------------------------------
class PullUpContainerDelegate extends PullUpMultiSetController {

    private var _view as PullUpContainerView;

    // Drag tracking
    private var _isDragging as Boolean = false;
    private var _lastTouchY as Number  = 0;
    private var _screenH    as Number  = 390;

    // Smooth snap animation timer
    private var _animTimer as Timer.Timer?;

    // --- Page 0 (Quick Set) Workout Engine ---
    private var _quickDetector       as PullUpDetector;
    private var _quickIsRecording    as Boolean = false;
    private var _quickUiTimer        as Timer.Timer?;
    private var _quickSeconds        as Number = 0;
    private var _quickSampleRate     as Number = 100;
    private var _quickHapticPending  as Boolean = false;
    private var _quickSession        as ActivityRecording.Session?;
    private var _quickSensorLogger   as SensorLogging.SensorLogger?;
    private var _quickTotalRepsField as FitContributor.Field?;
    private var _quickLapRepsField   as FitContributor.Field?;

    // --- Page 1 (Multi-Set) Workout Engine ---
    private var _multiDetector       as PullUpDetector;
    private var _multiCurrentSet     as Number = 1;
    private var _multiTotalReps      as Number = 0;
    private var _multiIsRecording    as Boolean = false;
    private var _multiHapticPending  as Boolean = false;
    private var _multiUiTimer        as Timer.Timer?;
    private var _multiSeconds        as Number = 0;
    private var _multiSampleRate     as Number = 100;
    private var _multiSession        as ActivityRecording.Session?;
    private var _multiSensorLogger   as SensorLogging.SensorLogger?;
    private var _multiTotalRepsField as FitContributor.Field?;
    private var _multiLapRepsField   as FitContributor.Field?;

    function initialize(view as PullUpContainerView) {
        BehaviorDelegate.initialize();
        _view = view;

        var dev = System.getDeviceSettings();
        if (dev.screenHeight != null && dev.screenHeight > 0) {
            _screenH = dev.screenHeight;
        }

        _quickDetector = new PullUpDetector();
        _multiDetector = new PullUpDetector();
    }

    // --- Touch Dragging (Real-time finger tracking) ---
    function onDrag(dragEvent as WatchUi.DragEvent) as Boolean {
        if (_quickIsRecording || _multiIsRecording) {
            return true;
        }

        var type = dragEvent.getType();
        var coords = dragEvent.getCoordinates();
        var currentY = coords[1];

        if (type == WatchUi.DRAG_TYPE_START) {
            _stopAnimation();
            _isDragging = true;
            _lastTouchY = currentY;
            _view.resetIndicatorTimer();
            return true;
        } else if (type == WatchUi.DRAG_TYPE_CONTINUE) {
            if (_isDragging) {
                var deltaY = _lastTouchY - currentY;
                _lastTouchY = currentY;

                var newScrollY = _view.getScrollY() + deltaY;
                var maxScroll = 2 * _screenH;

                // Clamp scroll offset within [0, 2 * _screenH]
                if (newScrollY < 0) {
                    newScrollY = 0;
                } else if (newScrollY > maxScroll) {
                    newScrollY = maxScroll;
                }

                _view.setScrollY(newScrollY);
                _view.resetIndicatorTimer();
                WatchUi.requestUpdate();
                return true;
            }
        } else if (type == WatchUi.DRAG_TYPE_STOP) {
            if (_isDragging) {
                _isDragging = false;
                _snapToClosestPage();
                return true;
            }
        }
        return false;
    }

    // Quick swipe / flick support
    function onFlick(flickEvent as WatchUi.FlickEvent) as Boolean {
        if (_quickIsRecording || _multiIsRecording) {
            return true;
        }

        var dir = flickEvent.getDirection();
        // Direction in degrees: 0 = up (scroll down to next page), 180 = down (scroll up to previous page)
        if (dir >= 315 || dir <= 45) {
            // Flick up -> go to next page
            return onNextPage();
        } else if (dir >= 135 && dir <= 225) {
            // Flick down -> go to previous page
            return onPreviousPage();
        }
        return false;
    }

    // --- Smooth Snap Animation ---
    private function _snapToClosestPage() as Void {
        var currentY = _view.getScrollY();
        var targetPage = (currentY + (_screenH / 2)) / _screenH;
        if (targetPage < 0) { targetPage = 0; }
        if (targetPage > 2) { targetPage = 2; }

        _animateToY(targetPage * _screenH);
    }

    private function _animateToY(targetY as Number) as Void {
        _stopAnimation();
        _view.setTargetScrollY(targetY);

        _animTimer = new Timer.Timer();
        _animTimer.start(method(:_onAnimStep), 16, true); // ~60 fps
    }

    public function _onAnimStep() as Void {
        var curr = _view.getScrollY();
        var target = _view.getTargetScrollY();
        var diff = target - curr;

        if (diff.abs() <= 3) {
            _view.setScrollY(target);
            _stopAnimation();
            _view.resetIndicatorTimer();
            WatchUi.requestUpdate();
            return;
        }

        // Spring/ease-out step
        var step = diff / 3;
        if (step == 0) {
            step = (diff > 0) ? 1 : -1;
        }

        _view.setScrollY(curr + step);
        _view.resetIndicatorTimer();
        WatchUi.requestUpdate();
    }

    private function _stopAnimation() as Void {
        if (_animTimer != null) {
            _animTimer.stop();
            _animTimer = null;
        }
    }

    // --- Hardware Button Navigation ---
    function onKey(keyEvent as WatchUi.KeyEvent) as Boolean {
        var key = keyEvent.getKey();

        if (key == WatchUi.KEY_ENTER || key == WatchUi.KEY_START) {
            return onSelect();
        } else if (key == WatchUi.KEY_DOWN) {
            if (!_quickIsRecording && !_multiIsRecording) {
                return onNextPage();
            }
            return true;
        } else if (key == WatchUi.KEY_UP) {
            if (!_quickIsRecording && !_multiIsRecording) {
                return onPreviousPage();
            }
            return true;
        }
        return BehaviorDelegate.onKey(keyEvent);
    }

    function onNextPage() as Boolean {
        if (_quickIsRecording || _multiIsRecording) {
            return true;
        }
        var page = _view.getActivePageIndex();
        if (page < 2) {
            _animateToY((page + 1) * _screenH);
            return true;
        }
        return false;
    }

    function onPreviousPage() as Boolean {
        if (_quickIsRecording || _multiIsRecording) {
            return true;
        }
        var page = _view.getActivePageIndex();
        if (page > 0) {
            _animateToY((page - 1) * _screenH);
            return true;
        }
        return false;
    }

    // --- Action Selection (START / SELECT) ---
    function onSelect() as Boolean {
        var page = _view.getActivePageIndex();

        if (page == 0) {
            // Quick Set toggle
            if (_quickIsRecording) {
                _stopQuickSet();
            } else {
                _startQuickSet();
            }
            return true;
        } else if (page == 1) {
            // Multi-Set toggle
            if (_multiIsRecording) {
                _stopMultiSet();
            } else {
                _startMultiSet();
            }
            return true;
        }
        return false;
    }

    // =========================================================================
    // QUICK SET ENGINE (PAGE 0)
    // =========================================================================
    private function _startQuickSet() as Void {
        // High-frequency accelerometer data is recorded and simulated at 100 Hz baseline.
        _quickSampleRate = 100;
        _quickDetector.start(_quickSampleRate);
        _quickSeconds       = 0;
        _quickHapticPending = false;
        _quickIsRecording   = true;

        _quickSensorLogger = new SensorLogging.SensorLogger({ :accelerometer => { :enabled => true } });
        _quickSession = ActivityRecording.createSession({
            :name         => "PullUp Quick Set",
            :sport        => Activity.SPORT_TRAINING,
            :subSport     => Activity.SUB_SPORT_STRENGTH_TRAINING,
            :sensorLogger => _quickSensorLogger
        });

        _quickTotalRepsField = _quickSession.createField("Total Reps", 0, FitContributor.DATA_TYPE_UINT16,
            { :mesgType => FitContributor.MESG_TYPE_SESSION, :units => "reps" });
        _quickLapRepsField   = _quickSession.createField("Set Reps", 1, FitContributor.DATA_TYPE_UINT16,
            { :mesgType => FitContributor.MESG_TYPE_LAP, :units => "reps" });

        _quickLapRepsField.setData(0);
        _quickTotalRepsField.setData(0);
        _quickSession.start();

        Sensor.registerSensorDataListener(method(:onQuickSensorData), {
            :period        => 1,
            :accelerometer => { :enabled => true, :sampleRate => _quickSampleRate }
        });

        _quickUiTimer = new Timer.Timer();
        _quickUiTimer.start(method(:onQuickUiTimer), 1000, true);

        _view.setQuickStatus("RECORDING...");
        _view.setQuickRecording(true);
        _updateQuickUi();
        System.println("PullUpContainer: Quick Set recording started");
    }

    private function _stopQuickSet() as Void {
        _quickIsRecording = false;

        if (_quickUiTimer != null) {
            _quickUiTimer.stop();
            _quickUiTimer = null;
        }

        Sensor.unregisterSensorDataListener();

        var detectedReps = _quickDetector.getRepCount();
        if (_quickLapRepsField != null) {
            _quickLapRepsField.setData(detectedReps);
        }
        if (_quickTotalRepsField != null) {
            _quickTotalRepsField.setData(detectedReps);
        }

        var sessionToPass = _quickSession;
        _quickSession      = null;
        _quickSensorLogger = null;

        _view.setQuickRecording(false);
        WatchUi.requestUpdate();

        var editView     = new PullUpEditView(detectedReps, false, 1);
        var editDelegate = new PullUpEditDelegate(editView, sessionToPass, null, false, 1);
        editDelegate.setFitFields(_quickTotalRepsField, _quickLapRepsField);

        WatchUi.pushView(editView, editDelegate, WatchUi.SLIDE_UP);
    }

    public function onQuickUiTimer() as Void {
        if (!_quickIsRecording) { return; }
        _quickSeconds++;
        _updateQuickUi();
    }

    private function _updateQuickUi() as Void {
        var reps = _quickDetector.getRepCount();
        if (_quickLapRepsField != null) { _quickLapRepsField.setData(reps); }
        if (_quickTotalRepsField != null) { _quickTotalRepsField.setData(reps); }

        var m = _quickSeconds / 60;
        var s = _quickSeconds % 60;
        var timeStr = m.format("%02d") + ":" + s.format("%02d");

        if (_quickDetector.isSetLocked()) {
            _view.setQuickStatus("SET LOCKED");
        } else if (_quickDetector.getState() == STATE_MOUNT_SETTLING) {
            _view.setQuickStatus("SETTLING...");
        } else {
            _view.setQuickStatus("RECORDING...");
        }

        _view.setQuickRepCount(reps);
        _view.setQuickElapsedTime(timeStr);
        _view.setQuickSampleCount(_quickDetector.getSampleCount());
        WatchUi.requestUpdate();
    }

    public function onQuickSensorData(sensorData as Sensor.SensorData) as Void {
        if (!_quickIsRecording) { return; }

        try {
            var accelData = sensorData.accelerometerData;
            if (accelData == null) { return; }

            var xs = accelData.x;
            var ys = accelData.y;
            var zs = accelData.z;
            if (xs == null || ys == null || zs == null) { return; }

            var n = xs.size();
            if (ys.size() < n) { n = ys.size(); }
            if (zs.size() < n) { n = zs.size(); }

            var repChanged = false;
            for (var i = 0; i < n; i++) {
                if (xs[i] != null && ys[i] != null && zs[i] != null) {
                    var res = _quickDetector.processSample(xs[i].toNumber(), ys[i].toNumber(), zs[i].toNumber());
                    if (res == 1) {
                        _quickHapticPending = true;
                        repChanged = true;
                    } else if (res == -1) {
                        repChanged = true;
                    }
                }
            }

            if (_quickHapticPending) {
                _quickHapticPending = false;
                _triggerHaptic();
            }

            if (repChanged || _quickDetector.isSetLocked()) {
                _updateQuickUi();
            }
        } catch (e) {
            System.println("QuickSet sensor error: " + e.getErrorMessage());
        }
    }

    // =========================================================================
    // MULTI-SET ENGINE (PAGE 1)
    // =========================================================================
    private function _startMultiSet() as Void {
        if (_multiSession == null) {
            _multiSensorLogger = new SensorLogging.SensorLogger({ :accelerometer => { :enabled => true } });
            _multiSession = ActivityRecording.createSession({
                :name         => "PullUp Workout",
                :sport        => Activity.SPORT_TRAINING,
                :subSport     => Activity.SUB_SPORT_STRENGTH_TRAINING,
                :sensorLogger => _multiSensorLogger
            });

            _multiTotalRepsField = _multiSession.createField("Total Reps", 0, FitContributor.DATA_TYPE_UINT16,
                { :mesgType => FitContributor.MESG_TYPE_SESSION, :units => "reps" });
            _multiLapRepsField   = _multiSession.createField("Set Reps", 1, FitContributor.DATA_TYPE_UINT16,
                { :mesgType => FitContributor.MESG_TYPE_LAP, :units => "reps" });

            _multiSession.start();
        }

        _multiSampleRate = 100;
        _multiDetector.start(_multiSampleRate);
        _multiSeconds       = 0;
        _multiHapticPending = false;
        _multiIsRecording   = true;

        Sensor.registerSensorDataListener(method(:onMultiSensorData), {
            :period        => 1,
            :accelerometer => { :enabled => true, :sampleRate => _multiSampleRate }
        });

        _multiUiTimer = new Timer.Timer();
        _multiUiTimer.start(method(:onMultiUiTimer), 1000, true);

        _view.setMultiRecording(true);
        _updateMultiRecordingView();
        System.println("PullUpContainer: Multi-Set recording started");
    }

    private function _stopMultiSet() as Void {
        _multiIsRecording = false;

        if (_multiUiTimer != null) {
            _multiUiTimer.stop();
            _multiUiTimer = null;
        }

        Sensor.unregisterSensorDataListener();

        var detectedReps = _multiDetector.getRepCount();
        _view.setMultiRecording(false);
        WatchUi.requestUpdate();

        var editView     = new PullUpEditView(detectedReps, true, _multiCurrentSet);
        var editDelegate = new PullUpEditDelegate(editView, _multiSession, self, true, _multiCurrentSet);
        WatchUi.pushView(editView, editDelegate, WatchUi.SLIDE_UP);
    }

    public function onSetConfirmed(confirmedReps as Number) as Void {
        if (_multiSession != null && _multiSession.isRecording()) {
            if (_multiLapRepsField != null) {
                _multiLapRepsField.setData(confirmedReps);
            }
            _multiSession.addLap();
        }

        _multiTotalReps += confirmedReps;
        var setPrBeaten = PullUpStorage.checkSetPr(confirmedReps);
        PullUpStorage.addReps(confirmedReps);

        var finishedSet = _multiCurrentSet;
        _multiCurrentSet++;

        var restView     = new PullUpRestView(confirmedReps, _multiTotalReps, _multiCurrentSet);
        var restDelegate = new PullUpRestDelegate(restView, self);
        WatchUi.pushView(restView, restDelegate, WatchUi.SLIDE_UP);

        if (setPrBeaten) {
            var celebView = new PullUpCelebrationView(
                "BEST SET!",
                confirmedReps,
                confirmedReps.toString() + " REPS"
            );
            var celebDelegate = new PullUpCelebrationDelegate(celebView);
            WatchUi.pushView(celebView, celebDelegate, WatchUi.SLIDE_UP);
        }
    }

    public function onSetDiscarded() as Void {
        if (_multiSession != null && _multiSession.isRecording()) {
            if (_multiLapRepsField != null) {
                _multiLapRepsField.setData(0);
            }
            _multiSession.addLap();
        }

        _multiCurrentSet++;
        var restView     = new PullUpRestView(0, _multiTotalReps, _multiCurrentSet);
        var restDelegate = new PullUpRestDelegate(restView, self);
        WatchUi.pushView(restView, restDelegate, WatchUi.SLIDE_UP);
    }

    public function startNextSet() as Void {
        _startMultiSet();
    }

    public function finishWorkout() as Void {
        if (_multiSession != null) {
            if (_multiTotalRepsField != null) {
                _multiTotalRepsField.setData(_multiTotalReps);
            }
            if (_multiSession.isRecording()) {
                _multiSession.stop();
            }
            _multiSession.save();
            _multiSession        = null;
            _multiSensorLogger   = null;
            _multiTotalRepsField = null;
            _multiLapRepsField   = null;
        }

        var prResult = PullUpStorage.checkDayOrWeekPr();

        _multiCurrentSet = 1;
        _multiTotalReps  = 0;
        _view.setMultiRecording(false);
        _view.setMultiSetNum(1);
        _view.setMultiSetReps(0);
        _view.setMultiTotalReps(0);
        WatchUi.requestUpdate();

        if (prResult[:isPr] as Boolean) {
            var celebView = new PullUpCelebrationView(
                prResult[:title] as String,
                prResult[:value] as Number,
                prResult[:sub] as String
            );
            var celebDelegate = new PullUpCelebrationDelegate(celebView);
            WatchUi.pushView(celebView, celebDelegate, WatchUi.SLIDE_UP);
        }
    }

    public function discardWorkout() as Void {
        if (_multiSession != null) {
            _multiSession.discard();
            _multiSession        = null;
            _multiSensorLogger   = null;
            _multiTotalRepsField = null;
            _multiLapRepsField   = null;
        }

        _multiCurrentSet = 1;
        _multiTotalReps  = 0;
        _view.setMultiRecording(false);
        _view.setMultiSetNum(1);
        _view.setMultiSetReps(0);
        _view.setMultiTotalReps(0);
        WatchUi.requestUpdate();
    }

    public function getTotalReps() as Number {
        return _multiTotalReps;
    }

    public function onMultiUiTimer() as Void {
        if (!_multiIsRecording) { return; }
        _multiSeconds++;
        _updateMultiRecordingView();
    }

    private function _updateMultiRecordingView() as Void {
        var m = _multiSeconds / 60;
        var s = _multiSeconds % 60;
        var timeStr = m.format("%02d") + ":" + s.format("%02d");

        var statusInfo = "";
        if (_multiDetector.isSetLocked()) {
            statusInfo = "SET LOCKED";
        } else if (_multiDetector.getState() == STATE_MOUNT_SETTLING) {
            statusInfo = "SETTLING...";
        } else {
            statusInfo = "Samples: " + _multiDetector.getSampleCount();
        }

        _view.setMultiRecording(true);
        _view.setMultiSetNum(_multiCurrentSet);
        _view.setMultiSetReps(_multiDetector.getRepCount());
        _view.setMultiTotalReps(_multiTotalReps);
        _view.setMultiElapsedTime(timeStr);
        _view.setMultiSampleText(statusInfo);
        WatchUi.requestUpdate();
    }

    public function onMultiSensorData(sensorData as Sensor.SensorData) as Void {
        if (!_multiIsRecording) { return; }

        try {
            var accelData = sensorData.accelerometerData;
            if (accelData == null) { return; }

            var xs = accelData.x;
            var ys = accelData.y;
            var zs = accelData.z;
            if (xs == null || ys == null || zs == null) { return; }

            var n = xs.size();
            if (ys.size() < n) { n = ys.size(); }
            if (zs.size() < n) { n = zs.size(); }

            var repChanged = false;
            for (var i = 0; i < n; i++) {
                if (xs[i] != null && ys[i] != null && zs[i] != null) {
                    var res = _multiDetector.processSample(xs[i].toNumber(), ys[i].toNumber(), zs[i].toNumber());
                    if (res == 1) {
                        _multiHapticPending = true;
                        repChanged = true;
                    } else if (res == -1) {
                        repChanged = true;
                    }
                }
            }

            if (_multiHapticPending) {
                _multiHapticPending = false;
                _triggerHaptic();
            }

            if (repChanged || _multiDetector.isSetLocked()) {
                _updateMultiRecordingView();
            }
        } catch (e) {
            System.println("MultiSet sensor error: " + e.getErrorMessage());
        }
    }

    private function _triggerHaptic() as Void {
        try {
            if (Attention has :vibrate) {
                var vibeData = [new Attention.VibeProfile(50, 150)] as Array<Attention.VibeProfile>;
                Attention.vibrate(vibeData);
            }
        } catch (e) {
            System.println("Haptic error: " + e.getErrorMessage());
        }
    }
}
