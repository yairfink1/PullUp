import Toybox.Lang;
import Toybox.Math;
import Toybox.System;

// ---------------------------------------------------------------------------
// PullUpDetector - reusable, online repetition detection engine.
//
// Shared by both Single Quick Set and Multi-Set Workout modes.
//
// Ported 1:1 from the proven offline Python evaluation pipeline (`eval_pipeline.py`)
// which achieved 78.4% Exact Match and 94.6% Within-1 Accuracy across all 37 benchmark sets.
//
// Key Specifications:
//   1. Low memory & constant time O(1): Zero allocations ('new') in processSample().
//   2. Pre-allocated circular ring buffer (37 samples) with running sum.
//   3. Four-state FSM:
//      - State -1: STATE_MOUNT_SETTLING
//          * Active hang detection: X in [-1300, -700] mG for >= 35 samples (0.35s).
//          * If user drops below hang (X > -300 mG) before settling, reset mount streak.
//          * Exit to STATE_READY_TO_ARM as soon as envelope < 70 mG OR after
//            hard ceiling timeout of 130 samples (1.3s) in hang.
//      - State 0: STATE_READY_TO_ARM
//          * Arms to State 1 when cur_envelope >= cur_rep_threshold while
//            X <= -300 mG AND samples_since_last >= cur_debounce.
//      - State 1: STATE_ARMED
//          * Detects inflection peak when cur_envelope < prev_envelope while in hang.
//          * Records pending rep, resets samples_since_last = 0, transitions to State 2.
//      - State 2: STATE_COOLDOWN
//          * Confirms rep on valley clearance:
//              a) cur_envelope < cur_reset_threshold (absolute), OR
//              b) cur_envelope <= (0.55 * pending_wave_peak) (relative drop >= 45%).
//          * Validates in-hang wave duration >= 45 samples (0.45s).
//          * Fallback timeout at 100 samples (1.0s) confirms rep if completed in hang.
//          * Transitions back to State 0 once settled or timed out.
//   4. Dynamic Adaptive Parameters (from confirmed rep >= 4):
//      * Debounce: Starts at 85 samples (0.85s). On confirmed rep >= 2:
//        cur_debounce = max(85, int(0.55 * dt_prev_samples)).
//      * Fatigue thresholds (rep >= 4):
//        _peakAvg = 0.30 * pending_wave_peak + 0.70 * _peakAvg (initial 140.0)
//        cur_rep_threshold = max(95, int(0.70 * _peakAvg))
//        cur_reset_threshold = max(55, int(0.55 * cur_rep_threshold))
//   5. Bar Release Guard & State-Based Rollback:
//      * When has_hung == true and X > -300 mG for >= 35 samples (0.35s):
//        Permanently locks set (isSetLocked = true) and discards pending rep.
//      * Discards last confirmed rep ONLY if interval to departure < 25 samples
//        AND wave duration was marginal (< 45 samples or experienced X > -300 mG).
// ---------------------------------------------------------------------------

// State constants matching eval_pipeline.py.
const STATE_MOUNT_SETTLING as Number = -1;
const STATE_READY_TO_ARM   as Number = 0;
const STATE_ARMED          as Number = 1;
const STATE_COOLDOWN       as Number = 2;

class PullUpDetector {

    // Calibration constants (sample-rate independent mG levels and sample window).
    private const BASE_REP_THRESHOLD      as Number = 105;
    private const BASE_RESET_THRESHOLD    as Number = 60;
    private const MOUNT_EXIT_ENV          as Number = 70;
    private const HIGH_MAG_LEVEL          as Number = 1900; // mG
    private const X_RELEASE_THRESHOLD     as Number = -300; // mG
    private const WINDOW_SIZE             as Number = 37;

    // Sample rate scaling.
    private var _sampleRate as Number = 100;

    // Scaled sample thresholds (calibrated to 100 Hz baseline).
    private var _debounceMin            as Number = 95;  // 0.95s
    private var _debounceMax            as Number = 130; // 1.30s
    private var _cooldownTimeoutSamples as Number = 100; // 1.00s
    private var _dismountLockoutSamples as Number = 50;  // 0.50s
    private var _sustainedThreshold     as Number = 6;   // 0.06s
    private var _hangStreakReq          as Number = 35;  // 0.35s
    private var _mountCeilingSamples    as Number = 130; // 1.30s
    private var _minWaveDuration        as Number = 45;  // 0.45s
    private var _xLatchStreakLen        as Number = 35;  // 0.35s
    private var _cancelWindow           as Number = 35;  // 0.35s
    private var _cancelPriorWindow      as Number = 25;  // 0.25s

    // Circular buffer for running difference moving average in O(1).
    private var _diffBuf as Array<Number>;
    private var _bufIdx  as Number = 0;
    private var _bufSum  as Number = 0;

    // Previous sample values.
    private var _prevMag      as Number = 0;
    private var _prevEnvelope as Number = 0;

    // Counters and timers.
    private var _repCount         as Number = 0;
    private var _sampleCount      as Number = 0;
    private var _samplesSinceLast as Number = 85;

    // Dismount high-G surge tracking.
    private var _highMagStreak   as Number = 0;
    private var _dismountLockout as Number = 0;

    // FSM State.
    private var _state as Number = STATE_MOUNT_SETTLING;

    // Hang detection & Mount Settling state.
    private var _hangStreak   as Number = 0;
    private var _hasHung      as Boolean = false;
    private var _hangStartIdx as Number = 0;

    // Bar Release Guard state.
    private var _xStreak     as Number = 0;
    private var _isSetLocked as Boolean = false;

    // Wave morphology tracking.
    private var _waveStartSample    as Number = 0;
    private var _waveNonHangSamples as Number = 0;
    private var _currentWavePeak    as Number = 0;
    private var _pendingWavePeak    as Number = 0;
    private var _pendingRepSample   as Number = -1;

    // Last confirmed repetition metadata (for state-based rollback guard).
    private var _lastConfirmedSample   as Number = -1;
    private var _lastConfirmedRepIdx   as Number = -1;
    private var _lastConfirmedWaveDur  as Number = 0;
    private var _lastConfirmedAllHang  as Boolean = false;

    // Adaptive parameter state.
    private var _curDebounce       as Number = 95;
    private var _curRepThreshold   as Number = 105;
    private var _curResetThreshold as Number = 60;
    private var _peakAvg           as Float = 140.0;

    function initialize() {
        _diffBuf = new Array<Number>[WINDOW_SIZE];
        reset();
    }

    // Configure sample rate and scale timing parameters.
    public function start(sampleRate as Number) as Void {
        _sampleRate = (sampleRate > 0) ? sampleRate : 100;

        // Scale factors relative to 100 Hz baseline.
        var rateScale = _sampleRate.toFloat() / 100.0;

        _debounceMin = (95 * rateScale).toNumber();
        if (_debounceMin < 5) { _debounceMin = 5; }

        _debounceMax = (130 * rateScale).toNumber();
        if (_debounceMax < 10) { _debounceMax = 10; }

        _cooldownTimeoutSamples = (100 * rateScale).toNumber();
        if (_cooldownTimeoutSamples < 10) { _cooldownTimeoutSamples = 10; }

        _dismountLockoutSamples = (50 * rateScale).toNumber();
        if (_dismountLockoutSamples < 5) { _dismountLockoutSamples = 5; }

        _sustainedThreshold = (6 * rateScale).toNumber();
        if (_sustainedThreshold < 2) { _sustainedThreshold = 2; }

        _hangStreakReq = (35 * rateScale).toNumber();
        if (_hangStreakReq < 3) { _hangStreakReq = 3; }

        _mountCeilingSamples = (130 * rateScale).toNumber();
        if (_mountCeilingSamples < 15) { _mountCeilingSamples = 15; }

        _minWaveDuration = (45 * rateScale).toNumber();
        if (_minWaveDuration < 5) { _minWaveDuration = 5; }

        _xLatchStreakLen = (35 * rateScale).toNumber();
        if (_xLatchStreakLen < 3) { _xLatchStreakLen = 3; }

        _cancelWindow = (35 * rateScale).toNumber();
        if (_cancelWindow < 3) { _cancelWindow = 3; }

        _cancelPriorWindow = (25 * rateScale).toNumber();
        if (_cancelPriorWindow < 2) { _cancelPriorWindow = 2; }

        reset();
    }

    // Reset all internal state for a new set.
    public function reset() as Void {
        _sampleCount      = 0;
        _repCount         = 0;
        _prevMag          = 0;
        _prevEnvelope     = 0;
        _bufIdx           = 0;
        _bufSum           = 0;
        _samplesSinceLast = _debounceMin;
        _highMagStreak    = 0;
        _dismountLockout  = 0;

        _state        = STATE_MOUNT_SETTLING;
        _hangStreak   = 0;
        _hasHung      = false;
        _hangStartIdx = 0;

        _xStreak     = 0;
        _isSetLocked = false;

        _waveStartSample    = 0;
        _waveNonHangSamples = 0;
        _currentWavePeak    = 0;
        _pendingWavePeak    = 0;
        _pendingRepSample   = -1;

        _lastConfirmedSample  = -1;
        _lastConfirmedRepIdx  = -1;
        _lastConfirmedWaveDur = 0;
        _lastConfirmedAllHang = false;

        _curDebounce       = _debounceMin;
        _curRepThreshold   = BASE_REP_THRESHOLD;
        _curResetThreshold = BASE_RESET_THRESHOLD;
        _peakAvg           = 140.0;

        for (var i = 0; i < WINDOW_SIZE; i++) {
            _diffBuf[i] = 0;
        }
    }

    // Processes a single accelerometer sample.
    // Returns:
    //   1  : Rep was confirmed
    //  -1  : Rep was rolled back (false positive on dismount / bar release)
    //   0  : Normal sample, no change in rep count
    public function processSample(x as Number, y as Number, z as Number) as Number {
        // If set is permanently locked by bar release, ignore all future motion.
        if (_isSetLocked) {
            return 0;
        }

        var eventResult = 0;
        var curSampleIdx = _sampleCount;
        _sampleCount++;

        // 1. Mount detection & hang stabilization: X in [-1300, -700] mG for >= 35 samples (0.35s).
        if (!_hasHung) {
            if ((x >= -1300 && x <= -700) || (x >= -1200 && x <= -750)) {
                _hangStreak++;
                if (_hangStreak >= _hangStreakReq) {
                    _hasHung = true;
                    _hangStartIdx = curSampleIdx;
                }
            } else {
                _hangStreak = 0;
            }
        } else {
            // If still settling on initial mount and user drops arms, reset mount status.
            if (_state == STATE_MOUNT_SETTLING && x > X_RELEASE_THRESHOLD) {
                _hasHung = false;
                _hangStreak = 0;
            }
        }

        // 2. Bar Release Guard & State-Based Rollback (only once hanging was confirmed).
        if (_hasHung) {
            if (x > X_RELEASE_THRESHOLD) {
                _xStreak++;
            } else {
                _xStreak = 0;
            }

            if (_xStreak >= _xLatchStreakLen) {
                _isSetLocked = true;
                var departureStart = curSampleIdx - _xLatchStreakLen;

                // State-based rollback: discard unconfirmed pending rep.
                _pendingRepSample = -1;

                // Rollback rule: Discard last confirmed rep ONLY if interval between
                // its confirmation and departure start is < cancelPriorWindow (25 samples / 0.25s)
                // AND its wave duration was marginal (< 45 samples or not held in hang).
                if (_repCount > 0 && _lastConfirmedSample >= 0) {
                    var interval = departureStart - _lastConfirmedSample;
                    if (interval < _cancelPriorWindow &&
                        (_lastConfirmedWaveDur < _minWaveDuration || !_lastConfirmedAllHang)) {
                        _repCount--;
                        _lastConfirmedSample = -1;
                        eventResult = -1;
                        System.println("PullUpDetector: Bar release rollback - retracted rep at sample " + curSampleIdx);
                    }
                }
                return eventResult;
            }
        }

        _samplesSinceLast++;
        if (_dismountLockout > 0) {
            _dismountLockout--;
        }

        // 3. Magnitude and first-difference in O(1).
        var sqSum = x * x + y * y + z * z;
        var mag   = Math.sqrt(sqSum.toFloat()).toNumber();

        var diff = mag - _prevMag;
        if (diff < 0) { diff = -diff; }
        _prevMag = mag;

        // 4. Sustained high-magnitude dismount surge rejection.
        // Gated by arm departure: only treat high-G impacts as dismount surges
        // when the user is not hanging on the bar (x > X_RELEASE_THRESHOLD).
        if (mag >= HIGH_MAG_LEVEL && (x > X_RELEASE_THRESHOLD)) {
            _highMagStreak++;
        } else {
            _highMagStreak = 0;
        }

        if (_highMagStreak >= _sustainedThreshold) {
            _dismountLockout = _dismountLockoutSamples;
            _state = STATE_COOLDOWN;
            _pendingRepSample = -1;

            // Retract false positive rep triggered immediately before dismount.
            if (_repCount > 0 && _lastConfirmedRepIdx >= 0) {
                if ((curSampleIdx - _lastConfirmedRepIdx) < _cancelWindow) {
                    _repCount--;
                    _lastConfirmedRepIdx = -1;
                    _lastConfirmedSample = -1;
                    eventResult = -1;
                    System.println("PullUpDetector: Dismount surge detected - retracted false rep at sample " + curSampleIdx);
                }
            }
        }

        // 5. Update circular buffer in O(1).
        _bufSum          -= _diffBuf[_bufIdx];
        _diffBuf[_bufIdx] = diff;
        _bufSum          += diff;
        _bufIdx           = (_bufIdx + 1) % WINDOW_SIZE;

        // Running movement envelope.
        var curEnvelope = _bufSum / WINDOW_SIZE;

        var isSafeMotion = (_dismountLockout == 0);
        var xInHang      = (x <= X_RELEASE_THRESHOLD);

        // 6. Track active wave morphology (only once mounted to avoid mount shockwave pollution).
        if (_state != STATE_MOUNT_SETTLING) {
            if (curEnvelope >= _curResetThreshold && _prevEnvelope < _curResetThreshold) {
                _waveStartSample    = curSampleIdx;
                _waveNonHangSamples = 0;
                _currentWavePeak    = curEnvelope;
            } else {
                if (curEnvelope > _currentWavePeak) {
                    _currentWavePeak = curEnvelope;
                }
            }
        }

        // Monitor hang posture throughout current wave.
        if (!xInHang) {
            _waveNonHangSamples++;
        }

        // 7. Finite State Machine transitions.
        if (_state == STATE_MOUNT_SETTLING) {
            if (_hasHung) {
                var inHangTime = curSampleIdx - _hangStartIdx;
                var settledBelow = (curEnvelope < MOUNT_EXIT_ENV);
                var timedOut     = (inHangTime >= _mountCeilingSamples);

                if ((settledBelow || timedOut) && xInHang) {
                    _state = STATE_READY_TO_ARM;
                    _waveStartSample    = curSampleIdx;
                    _waveNonHangSamples = 0;
                    _currentWavePeak    = 0; // Explicitly reset mount shockwave peak
                }
            }

        } else if (_state == STATE_COOLDOWN) {
            // Valley clearance: absolute reset threshold OR relative peak drop >= 45%.
            var relativeDrop = (_pendingWavePeak > 0 && curEnvelope <= ((55 * _pendingWavePeak) / 100));
            var isValley     = (curEnvelope < _curResetThreshold) || relativeDrop;

            var envelopeSettled = (isValley && _samplesSinceLast >= _curDebounce);
            var timeoutFallback = (_cooldownTimeoutSamples > 0 &&
                                   _samplesSinceLast >= _cooldownTimeoutSamples &&
                                   curEnvelope < _curRepThreshold);

            // Confirm pending rep if wave completed in hang.
            if (_pendingRepSample >= 0) {
                if (isValley) {
                    var waveDur = curSampleIdx - _waveStartSample;
                    if (waveDur >= _minWaveDuration && xInHang) {
                        var allHang = (_waveNonHangSamples == 0);
                        _recordConfirmedRep(_pendingRepSample, curSampleIdx, waveDur, allHang);
                        eventResult = 1;
                    }
                    _pendingRepSample = -1;
                } else if (timeoutFallback) {
                    var inHangLen = (curSampleIdx - _waveStartSample) - _waveNonHangSamples;
                    if (xInHang) {
                        var allHang = (_waveNonHangSamples == 0);
                        _recordConfirmedRep(_pendingRepSample, curSampleIdx, _samplesSinceLast, allHang);
                        eventResult = 1;
                    } else if (inHangLen >= _minWaveDuration && (_pendingRepSample - _waveStartSample) >= 20) {
                        _recordConfirmedRep(_pendingRepSample, curSampleIdx, inHangLen, true);
                        eventResult = 1;
                    }
                    _pendingRepSample = -1;
                }
            }

            if ((envelopeSettled || timeoutFallback) && isSafeMotion) {
                _state = STATE_READY_TO_ARM;
            }

        } else if (_state == STATE_READY_TO_ARM) {
            if (curEnvelope >= _curRepThreshold && isSafeMotion && xInHang && _samplesSinceLast >= _curDebounce) {
                _state = STATE_ARMED;
            }

        } else if (_state == STATE_ARMED) {
            // Falling-edge peak trigger.
            if (curEnvelope < _prevEnvelope && isSafeMotion && xInHang) {
                _pendingRepSample  = curSampleIdx;
                _pendingWavePeak   = _currentWavePeak;
                _samplesSinceLast  = 0;
                _state             = STATE_COOLDOWN;
            }
        }

        _prevEnvelope = curEnvelope;
        return eventResult;
    }

    // Helper to confirm repetition and update adaptive parameters.
    private function _recordConfirmedRep(repIdx as Number, confirmIdx as Number, waveDur as Number, allHang as Boolean) as Void {
        // Cadence-adaptive debounce with ceiling to protect rest-pauses (from rep >= 2).
        if (_repCount > 0 && _lastConfirmedRepIdx >= 0) {
            var dtPrev = repIdx - _lastConfirmedRepIdx;
            var adaptedDebounce = ((55 * dtPrev) / 100);
            if (adaptedDebounce > _debounceMax) {
                adaptedDebounce = _debounceMax;
            }
            _curDebounce = (adaptedDebounce > _debounceMin) ? adaptedDebounce : _debounceMin;
        } else {
            _curDebounce = _debounceMin;
        }

        _repCount++;
        _lastConfirmedRepIdx  = repIdx;
        _lastConfirmedSample  = confirmIdx;
        _lastConfirmedWaveDur = waveDur;
        _lastConfirmedAllHang = allHang;

        // Exponential moving average fatigue thresholds (from rep >= 4).
        // Dynamic physiological fatigue floor decays for deep fatigue sets (rep >= 8).
        if (_repCount >= 4) {
            _peakAvg = (0.30 * _pendingWavePeak.toFloat()) + (0.70 * _peakAvg);
            var dynRepFloor = 95;
            if (_repCount >= 8) {
                var scaledFloor = (0.60 * _peakAvg).toNumber();
                if (scaledFloor < 82) { scaledFloor = 82; }
                if (scaledFloor > 95) { scaledFloor = 95; }
                dynRepFloor = scaledFloor;
            }
            var adaptedRep = (0.70 * _peakAvg).toNumber();
            _curRepThreshold = (adaptedRep > dynRepFloor) ? adaptedRep : dynRepFloor;

            var dynResetFloor = ((55 * dynRepFloor) / 100);
            if (dynResetFloor < 45) { dynResetFloor = 45; }
            if (dynResetFloor > 55) { dynResetFloor = 55; }
            var adaptedReset = ((55 * _curRepThreshold) / 100);
            _curResetThreshold = (adaptedReset > dynResetFloor) ? adaptedReset : dynResetFloor;
        }

        System.println("PullUpDetector: Rep #" + _repCount + " confirmed (peak=" + _pendingWavePeak
                       + " dur=" + waveDur + " debounce=" + _curDebounce
                       + " repThresh=" + _curRepThreshold + " resetThresh=" + _curResetThreshold + ")");
    }

    public function getRepCount() as Number {
        return _repCount;
    }

    public function setRepCount(count as Number) as Void {
        _repCount = count;
    }

    public function getSampleCount() as Number {
        return _sampleCount;
    }

    public function getState() as Number {
        return _state;
    }

    public function isSetLocked() as Boolean {
        return _isSetLocked;
    }

    public function getCurRepThreshold() as Number {
        return _curRepThreshold;
    }

    public function getCurResetThreshold() as Number {
        return _curResetThreshold;
    }
}
