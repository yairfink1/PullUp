import Toybox.Attention;
import Toybox.FitContributor;
import Toybox.Lang;
import Toybox.Sensor;
import Toybox.System;
import Toybox.Timer;
import Toybox.WatchUi;
import Toybox.ActivityRecording;
import Toybox.Activity;
import Toybox.SensorLogging;

// ---------------------------------------------------------------------------
// PullUpMultiSetDelegate - manages continuous multi-set workout session.
//
// Key Features:
//   - Continuous ActivityRecording session across multiple sets.
//   - Writes FitContributor Lap Developer Fields for each set.
//   - Writes FitContributor Session Developer Field at workout finish.
//   - Seamless transition to Rest screen between sets.
//   - Switching back to Single Quick Set view via UP when idle.
// ---------------------------------------------------------------------------
class PullUpMultiSetDelegate extends PullUpMultiSetController {

    private var _view     as PullUpMultiSetView;
    private var _detector as PullUpDetector;

    // Multi-set state.
    private var _currentSet   as Number = 1;
    private var _totalReps    as Number = 0;
    private var _isRecording  as Boolean = false;
    private var _hapticPending as Boolean = false;

    // Timing.
    private var _uiTimer    as Timer.Timer?;
    private var _setSeconds as Number = 0;
    private var _sampleRate as Number = 100;

    // Recording & FIT developer fields.
    private var _session        as ActivityRecording.Session?;
    private var _sensorLogger   as SensorLogging.SensorLogger?;
    private var _totalRepsField as FitContributor.Field?;
    private var _lapRepsField   as FitContributor.Field?;

    function initialize(view as PullUpMultiSetView) {
        BehaviorDelegate.initialize();
        _view     = view;
        _detector = new PullUpDetector();
        _updateIdleView();
    }

    // -- Physical Key Handler -----------------------------------------------

    function onKey(keyEvent as WatchUi.KeyEvent) as Boolean {
        var key = keyEvent.getKey();
        if (key == WatchUi.KEY_ENTER || key == WatchUi.KEY_START) {
            return onSelect();
        } else if (_isRecording && (key == WatchUi.KEY_UP || key == WatchUi.KEY_DOWN)) {
            // Block view switching while actively recording a set
            return true;
        }
        return BehaviorDelegate.onKey(keyEvent);
    }

    // SELECT / START - Start set or stop set.
    function onSelect() as Boolean {
        if (_isRecording) {
            _stopCurrentSet();
        } else {
            _startActiveSet();
        }
        return true;
    }

    // -- Set Control --------------------------------------------------------

    private function _startActiveSet() as Void {
        // Initialize continuous session on Set 1 if not already running.
        if (_session == null) {
            _sensorLogger = new SensorLogging.SensorLogger({ :accelerometer => { :enabled => true } });

            _session = ActivityRecording.createSession({
                :name         => "PullUp Workout",
                :sport        => Activity.SPORT_TRAINING,
                :subSport     => Activity.SUB_SPORT_STRENGTH_TRAINING,
                :sensorLogger => _sensorLogger
            });

            // Developer FIT fields — no :nativeNum to avoid conflicts with native
            // session/lap fields (e.g. nativeNum=7 collides with total_calories).
            // Data appears under "Connect IQ" in Garmin Connect.
            _totalRepsField = _session.createField("Total Reps", 0, FitContributor.DATA_TYPE_UINT16,
                { :mesgType => FitContributor.MESG_TYPE_SESSION, :units => "reps" });
            _lapRepsField   = _session.createField("Set Reps", 1, FitContributor.DATA_TYPE_UINT16,
                { :mesgType => FitContributor.MESG_TYPE_LAP, :units => "reps" });

            _session.start();
            System.println("PullUpMultiSet: Session started.");
        }

        // Determine sample rate.
        _sampleRate = 100;
        if (Sensor has :getMaxSampleRate) {
            var maxRate = Sensor.getMaxSampleRate();
            if (maxRate != null && maxRate > 0) {
                _sampleRate = (maxRate >= 100) ? 100 : maxRate;
            }
        }

        _detector.start(_sampleRate);
        _setSeconds    = 0;
        _hapticPending = false;
        _isRecording   = true;

        // Register online sensor listener.
        var options = {
            :period        => 1,
            :accelerometer => { :enabled => true, :sampleRate => _sampleRate }
        };
        Sensor.registerSensorDataListener(method(:onSensorData), options);

        // Start UI decoupling timer.
        _uiTimer = new Timer.Timer();
        _uiTimer.start(method(:onUiTimer), 1000, true);

        _updateRecordingView();
        System.println("PullUpMultiSet: Set " + _currentSet + " recording started.");
    }

    private function _stopCurrentSet() as Void {
        _isRecording = false;

        if (_uiTimer != null) {
            _uiTimer.stop();
            _uiTimer = null;
        }

        Sensor.unregisterSensorDataListener();

        var detectedReps = _detector.getRepCount();
        System.println("PullUpMultiSet: Set " + _currentSet + " stopped. Reps detected: " + detectedReps);

        // Push EditView in multi-set mode with detected exercise name.
        var exName       = _detector.getExerciseName();
        var editView     = new PullUpEditView(detectedReps, true, _currentSet, exName);
        var editDelegate = new PullUpEditDelegate(editView, _session, self, true, _currentSet);
        WatchUi.pushView(editView, editDelegate, WatchUi.SLIDE_UP);
    }

    // Called by PullUpEditDelegate when set is confirmed.
    public function onSetConfirmed(confirmedReps as Number) as Void {
        if (_session != null && _session.isRecording()) {
            if (_lapRepsField != null) {
                _lapRepsField.setData(confirmedReps);
            }
            _session.addLap();
        }

        _totalReps += confirmedReps;
        PullUpStorage.addReps(confirmedReps);

        var finishedSet = _currentSet;
        _currentSet++;

        System.println("PullUpMultiSet: Set " + finishedSet + " confirmed with " + confirmedReps
                       + " reps. Total workout reps: " + _totalReps);

        // Transition to live rest screen.
        var restView     = new PullUpRestView(confirmedReps, _totalReps, _currentSet);
        var restDelegate = new PullUpRestDelegate(restView, self);
        WatchUi.pushView(restView, restDelegate, WatchUi.SLIDE_UP);
    }

    // Called by PullUpEditDelegate if set is discarded.
    public function onSetDiscarded() as Void {
        if (_session != null && _session.isRecording()) {
            if (_lapRepsField != null) {
                _lapRepsField.setData(0);
            }
            _session.addLap();
        }

        var finishedSet = _currentSet;
        _currentSet++;
        System.println("PullUpMultiSet: Set " + finishedSet + " discarded.");

        var restView     = new PullUpRestView(0, _totalReps, _currentSet);
        var restDelegate = new PullUpRestDelegate(restView, self);
        WatchUi.pushView(restView, restDelegate, WatchUi.SLIDE_UP);
    }

    // Called by PullUpRestDelegate when START is pressed during rest.
    public function startNextSet() as Void {
        _startActiveSet();
    }

    // Called when workout is finished and committed.
    public function finishWorkout() as Void {
        if (_session != null) {
            if (_totalRepsField != null) {
                _totalRepsField.setData(_totalReps);
            }
            if (_session.isRecording()) {
                _session.stop();
            }
            _session.save();
            System.println("PullUpMultiSet: Workout finished & saved. Total reps: " + _totalReps);
            _session        = null;
            _sensorLogger   = null;
            _totalRepsField = null;
            _lapRepsField   = null;
        }

        _currentSet = 1;
        _totalReps  = 0;
        _updateIdleView();
    }

    // Called when workout is completely discarded.
    public function discardWorkout() as Void {
        if (_session != null) {
            _session.discard();
            System.println("PullUpMultiSet: Workout discarded.");
            _session        = null;
            _sensorLogger   = null;
            _totalRepsField = null;
            _lapRepsField   = null;
        }

        _currentSet = 1;
        _totalReps  = 0;
        _updateIdleView();
    }

    public function getTotalReps() as Number {
        return _totalReps;
    }

    // -- Periodic UI Timer --------------------------------------------------

    public function onUiTimer() as Void {
        if (!_isRecording) {
            return;
        }
        _setSeconds++;
        _updateRecordingView();
    }

    private function _updateRecordingView() as Void {
        var m = _setSeconds / 60;
        var s = _setSeconds % 60;
        var timeStr = m.format("%02d") + ":" + s.format("%02d");

        var statusInfo = "";
        if (_detector.isSetLocked()) {
            statusInfo = "SET LOCKED";
        } else if (_detector.getState() == STATE_MOUNT_SETTLING) {
            statusInfo = "SETTLING...";
        } else {
            statusInfo = "Samples: " + _detector.getSampleCount();
        }

        _view.setRecording(true);
        _view.setCurrentSet(_currentSet);
        _view.setSetReps(_detector.getRepCount());
        _view.setTotalReps(_totalReps);
        _view.setElapsedTime(timeStr);
        _view.setSampleText(statusInfo);
        WatchUi.requestUpdate();
    }

    private function _updateIdleView() as Void {
        _view.setRecording(false);
        _view.setCurrentSet(_currentSet);
        _view.setSetReps(0);
        _view.setTotalReps(_totalReps);
        WatchUi.requestUpdate();
    }

    // -- Sensor Data Handler ------------------------------------------------

    public function onSensorData(sensorData as Sensor.SensorData) as Void {
        if (!_isRecording) {
            return;
        }

        try {
            var accelData = sensorData.accelerometerData;
            if (accelData == null) {
                return;
            }

            var xs = accelData.x;
            var ys = accelData.y;
            var zs = accelData.z;
            if (xs == null || ys == null || zs == null) {
                return;
            }

            var n = xs.size();
            if (ys.size() < n) { n = ys.size(); }
            if (zs.size() < n) { n = zs.size(); }

            var repChanged = false;
            for (var i = 0; i < n; i++) {
                if (xs[i] != null && ys[i] != null && zs[i] != null) {
                    var res = _detector.processSample(xs[i].toNumber(), ys[i].toNumber(), zs[i].toNumber());
                    if (res == 1) {
                        _hapticPending = true;
                        repChanged = true;
                    } else if (res == -1) {
                        repChanged = true;
                    }
                }
            }

            if (_hapticPending) {
                _hapticPending = false;
                _triggerHaptic();
            }

            if (repChanged || _detector.isSetLocked()) {
                _updateRecordingView();
            }
        } catch (e) {
            System.println("PullUpMultiSet onSensorData error: " + e.getErrorMessage());
        }
    }

    private function _triggerHaptic() as Void {
        try {
            if (Attention has :vibrate) {
                var vibeData = [new Attention.VibeProfile(50, 150)] as Array<Attention.VibeProfile>;
                Attention.vibrate(vibeData);
            }
        } catch (e) {
            System.println("PullUpMultiSet haptic error: " + e.getErrorMessage());
        }
    }
}
