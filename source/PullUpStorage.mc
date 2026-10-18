import Toybox.Application.Storage;
import Toybox.Lang;
import Toybox.System;
import Toybox.Time;
import Toybox.Time.Gregorian;

// ---------------------------------------------------------------------------
// PullUpStorage - persistent daily, weekly, and rolling 7-day tracking.
//
// Annotated with (:glance) so it can be loaded in glance mode without
// pulling in non-glance application logic.
// ---------------------------------------------------------------------------
(:glance)
module PullUpStorage {

    const KEY_DATE          as String = "pullup_date_key";
    const KEY_REPS          as String = "pullup_today_reps";
    const KEY_WEEK_DATE     as String = "pullup_week_key";
    const KEY_WEEK_REPS     as String = "pullup_week_reps";
    const KEY_HISTORY_ARRAY as String = "pullup_7day_history";
    const KEY_HISTORY_DATE  as String = "pullup_history_date";
    const KEY_HISTORY_MOMENT as String = "pullup_history_moment";

    // Personal Records (all-time records).
    const KEY_PR_SET             as String = "pullup_pr_set";
    const KEY_PR_DAY             as String = "pullup_pr_day";
    const KEY_PR_WEEK            as String = "pullup_pr_week";
    const KEY_PR_DAY_CELEB_DATE  as String = "pullup_pr_day_celeb_date";
    const KEY_PR_WEEK_CELEB_DATE as String = "pullup_pr_week_celeb_date";

    const DAY_LETTERS as Array<String> = ["S", "M", "T", "W", "T", "F", "S"];

    // Returns all-time single-set personal record.
    function getPrSet() as Number {
        var val = Storage.getValue(KEY_PR_SET);
        return (val instanceof Number) ? (val as Number) : 0;
    }

    // Returns all-time single-day personal record.
    function getPrDay() as Number {
        var val = Storage.getValue(KEY_PR_DAY);
        return (val instanceof Number) ? (val as Number) : 0;
    }

    // Returns all-time single-week personal record.
    function getPrWeek() as Number {
        var val = Storage.getValue(KEY_PR_WEEK);
        return (val instanceof Number) ? (val as Number) : 0;
    }

    // Returns today's cumulative rep count, resetting to 0 if the date rolled over.
    function getTodayReps() as Number {
        var arr = _getHistoryArray();
        return arr[6];
    }

    // Returns this week's cumulative rep count (starting Sunday), resetting to 0 if the week rolled over.
    function getWeekReps() as Number {
        var weekKey = getWeekKey();
        var savedWeek = Storage.getValue(KEY_WEEK_DATE);

        if (savedWeek == null) {
            return 0;
        }

        if (!(savedWeek instanceof Number) || (savedWeek as Number) != weekKey) {
            Storage.setValue(KEY_WEEK_DATE, weekKey);
            Storage.setValue(KEY_WEEK_REPS, 0);
            return 0;
        }

        var reps = Storage.getValue(KEY_WEEK_REPS);
        if (reps == null || !(reps instanceof Number)) {
            return 0;
        }
        return reps as Number;
    }

    // Returns internal 7-day array [day_minus_6, ..., day_minus_1, today], handling day rollover.
    function _getHistoryArray() as Array<Number> {
        var todayKey = getTodayKey();
        var savedDate = Storage.getValue(KEY_HISTORY_DATE);
        var rawArray  = Storage.getValue(KEY_HISTORY_ARRAY);

        if (savedDate == null || rawArray == null) {
            var existingDate = Storage.getValue(KEY_DATE);
            var existingReps = Storage.getValue(KEY_REPS);

            if (existingDate instanceof Number && (existingDate as Number) == todayKey && existingReps instanceof Number) {
                // User updating app: preserve their actual today reps!
                var arrMigrate = [0, 0, 0, 0, 0, 0, existingReps as Number] as Array<Number>;
                Storage.setValue(KEY_HISTORY_DATE, todayKey);
                Storage.setValue(KEY_HISTORY_MOMENT, Time.now().value());
                Storage.setValue(KEY_HISTORY_ARRAY, arrMigrate);
                rawArray = arrMigrate;
                savedDate = todayKey;
                System.println("PullUpStorage: preserved existing today reps (" + existingReps + ") on app update");
            } else {
                // First-time fresh install: start clean with 0 reps
                var arrClean = [0, 0, 0, 0, 0, 0, 0] as Array<Number>;
                Storage.setValue(KEY_HISTORY_DATE, todayKey);
                Storage.setValue(KEY_HISTORY_MOMENT, Time.now().value());
                Storage.setValue(KEY_HISTORY_ARRAY, arrClean);
                Storage.setValue(KEY_DATE, todayKey);
                Storage.setValue(KEY_REPS, 0);
                Storage.setValue(KEY_WEEK_DATE, getWeekKey());
                Storage.setValue(KEY_WEEK_REPS, 0);
                rawArray = arrClean;
                savedDate = todayKey;
                System.println("PullUpStorage: fresh install initialized with 0 reps");
            }
        }

        var arr = [0, 0, 0, 0, 0, 0, 0] as Array<Number>;
        if (rawArray instanceof Array) {
            var src = rawArray as Array;
            for (var i = 0; i < 7 && i < src.size(); i++) {
                if (src[i] instanceof Number) {
                    arr[i] = src[i] as Number;
                }
            }
        }

        if (!(savedDate instanceof Number) || (savedDate as Number) != todayKey) {
            var savedMoment = Storage.getValue(KEY_HISTORY_MOMENT);
            var nowVal = Time.now().value();
            var daysDiff = 1;

            if (savedMoment instanceof Number) {
                var diffSec = nowVal - (savedMoment as Number);
                if (diffSec > 0) {
                    daysDiff = diffSec / 86400;
                    if (daysDiff < 1) { daysDiff = 1; }
                }
            }

            if (daysDiff >= 7) {
                arr = [0, 0, 0, 0, 0, 0, 0] as Array<Number>;
            } else {
                var shifted = [0, 0, 0, 0, 0, 0, 0] as Array<Number>;
                for (var k = 0; k < 7 - daysDiff; k++) {
                    shifted[k] = arr[k + daysDiff];
                }
                arr = shifted;
            }

            Storage.setValue(KEY_HISTORY_DATE, todayKey);
            Storage.setValue(KEY_HISTORY_MOMENT, nowVal);
            Storage.setValue(KEY_HISTORY_ARRAY, arr);
            Storage.setValue(KEY_DATE, todayKey);
            Storage.setValue(KEY_REPS, arr[6]);
        }

        return arr;
    }

    // Returns an array of 7 dictionaries: [{ :dayLetter => "M", :reps => count, :isToday => boolean }].
    function getRolling7Days() as Array<Dictionary<Symbol, Object>> {
        var arr = _getHistoryArray();
        var now = Time.now();
        var result = new [7] as Array<Dictionary<Symbol, Object>>;

        for (var i = 0; i < 7; i++) {
            var daysAgo = 6 - i;
            var dayMoment = (daysAgo == 0) ? now : now.subtract(new Time.Duration(daysAgo * 86400));
            var info = Gregorian.info(dayMoment, Time.FORMAT_SHORT);
            var dayIndex = info.day_of_week - 1;
            if (dayIndex < 0 || dayIndex > 6) { dayIndex = 0; }
            var letter = DAY_LETTERS[dayIndex];

            result[i] = {
                :dayLetter => letter,
                :reps      => arr[i],
                :isToday   => (i == 6)
            };
        }

        return result;
    }

    // Adds completed reps to both today's (arr[6]) and this week's cumulative totals.
    function addReps(repsToAdd as Number) as Void {
        if (repsToAdd <= 0) {
            return;
        }

        var arr = _getHistoryArray();
        arr[6] = arr[6] + repsToAdd;

        var todayKey = getTodayKey();
        var nowVal   = Time.now().value();

        Storage.setValue(KEY_HISTORY_DATE, todayKey);
        Storage.setValue(KEY_HISTORY_MOMENT, nowVal);
        Storage.setValue(KEY_HISTORY_ARRAY, arr);
        Storage.setValue(KEY_DATE, todayKey);
        Storage.setValue(KEY_REPS, arr[6]);

        // -- This Week --
        var weekKey = getWeekKey();
        var savedWeek = Storage.getValue(KEY_WEEK_DATE);
        var currentWeek = 0;
        if (savedWeek instanceof Number && (savedWeek as Number) == weekKey) {
            var storedWeek = Storage.getValue(KEY_WEEK_REPS);
            currentWeek = (storedWeek instanceof Number) ? (storedWeek as Number) : 0;
        }
        var updatedWeek = currentWeek + repsToAdd;
        Storage.setValue(KEY_WEEK_DATE, weekKey);
        Storage.setValue(KEY_WEEK_REPS, updatedWeek);

        System.println("PullUpStorage: added " + repsToAdd + " reps. Today: " + arr[6] + ", Week: " + updatedWeek);
    }

    // Adds completed reps and checks if any PR was established or beaten.
    function addRepsWithPrCheck(repsToAdd as Number, isSingleSet as Boolean) as Dictionary<Symbol, Object> {
        var result = {
            :isPr  => false,
            :type  => null,
            :value => 0,
            :title => "",
            :sub   => ""
        } as Dictionary<Symbol, Object>;

        if (repsToAdd <= 0) {
            return result;
        }

        var oldSetPr  = getPrSet();
        var oldDayPr  = getPrDay();
        var oldWeekPr = getPrWeek();

        // Commit reps to rolling 7-day array, today total, and week total.
        addReps(repsToAdd);

        var todayReps = getTodayReps();
        var weekReps  = getWeekReps();

        var isSetPr  = (isSingleSet && repsToAdd > oldSetPr);
        var isDayPr  = (todayReps > oldDayPr);
        var isWeekPr = (weekReps > oldWeekPr);

        if (isSetPr) {
            Storage.setValue(KEY_PR_SET, repsToAdd);
        }
        if (isDayPr) {
            Storage.setValue(KEY_PR_DAY, todayReps);
        }
        if (isWeekPr) {
            Storage.setValue(KEY_PR_WEEK, weekReps);
        }

        var todayKey = getTodayKey();
        var weekKey  = getWeekKey();

        var lastDayCeleb  = Storage.getValue(KEY_PR_DAY_CELEB_DATE);
        var canCelebDay   = (lastDayCeleb == null || (lastDayCeleb as Number) != todayKey);

        var lastWeekCeleb = Storage.getValue(KEY_PR_WEEK_CELEB_DATE);
        var canCelebWeek  = (lastWeekCeleb == null || (lastWeekCeleb as Number) != weekKey);

        if (isSetPr) {
            result[:isPr]  = true;
            result[:type]  = :set;
            result[:value] = repsToAdd;
            result[:title] = "BEST SET!";
            result[:sub]   = repsToAdd.toString() + " REPS";
            System.println("PullUpStorage: NEW SET PR! " + repsToAdd + " reps (previous: " + oldSetPr + ")");
        } else if (isDayPr && oldDayPr > 0 && canCelebDay) {
            Storage.setValue(KEY_PR_DAY_CELEB_DATE, todayKey);
            result[:isPr]  = true;
            result[:type]  = :day;
            result[:value] = todayReps;
            result[:title] = "BEST DAY!";
            result[:sub]   = todayReps.toString() + " REPS TODAY";
            System.println("PullUpStorage: NEW DAY PR! " + todayReps + " reps (previous: " + oldDayPr + ")");
        } else if (isWeekPr && oldWeekPr > 0 && canCelebWeek) {
            Storage.setValue(KEY_PR_WEEK_CELEB_DATE, weekKey);
            result[:isPr]  = true;
            result[:type]  = :week;
            result[:value] = weekReps;
            result[:title] = "BEST WEEK!";
            result[:sub]   = weekReps.toString() + " REPS THIS WEEK";
            System.println("PullUpStorage: NEW WEEK PR! " + weekReps + " reps (previous: " + oldWeekPr + ")");
        }

        return result;
    }

    // Checks if a set beat the all-time Set PR, updating it if so.
    function checkSetPr(reps as Number) as Boolean {
        if (reps <= 0) {
            return false;
        }
        var oldSetPr = getPrSet();
        if (reps > oldSetPr) {
            Storage.setValue(KEY_PR_SET, reps);
            System.println("PullUpStorage: NEW SET PR! " + reps + " reps (was " + oldSetPr + ")");
            return true;
        }
        return false;
    }

    // Checks if today's or this week's totals beat all-time records, updating if so.
    function checkDayOrWeekPr() as Dictionary<Symbol, Object> {
        var result = {
            :isPr  => false,
            :type  => null,
            :value => 0,
            :title => "",
            :sub   => ""
        } as Dictionary<Symbol, Object>;

        var todayReps = getTodayReps();
        var oldDayPr  = getPrDay();
        var weekReps  = getWeekReps();
        var oldWeekPr = getPrWeek();

        var todayKey = getTodayKey();
        var weekKey  = getWeekKey();

        var lastDayCeleb  = Storage.getValue(KEY_PR_DAY_CELEB_DATE);
        var canCelebDay   = (lastDayCeleb == null || (lastDayCeleb as Number) != todayKey);

        var lastWeekCeleb = Storage.getValue(KEY_PR_WEEK_CELEB_DATE);
        var canCelebWeek  = (lastWeekCeleb == null || (lastWeekCeleb as Number) != weekKey);

        if (todayReps > oldDayPr) {
            Storage.setValue(KEY_PR_DAY, todayReps);
            if (oldDayPr > 0 && canCelebDay) {
                Storage.setValue(KEY_PR_DAY_CELEB_DATE, todayKey);
                result[:isPr]  = true;
                result[:type]  = :day;
                result[:value] = todayReps;
                result[:title] = "BEST DAY!";
                result[:sub]   = todayReps.toString() + " REPS TODAY";
                System.println("PullUpStorage: NEW DAY PR! " + todayReps + " reps (was " + oldDayPr + ")");
                return result;
            }
        }

        if (weekReps > oldWeekPr) {
            Storage.setValue(KEY_PR_WEEK, weekReps);
            if (oldWeekPr > 0 && canCelebWeek) {
                Storage.setValue(KEY_PR_WEEK_CELEB_DATE, weekKey);
                result[:isPr]  = true;
                result[:type]  = :week;
                result[:value] = weekReps;
                result[:title] = "BEST WEEK!";
                result[:sub]   = weekReps.toString() + " REPS THIS WEEK";
                System.println("PullUpStorage: NEW WEEK PR! " + weekReps + " reps (was " + oldWeekPr + ")");
                return result;
            }
        }

        return result;
    }

    // Computes unique integer representation of current day: YYYYMMDD.
    function getTodayKey() as Number {
        var now = Time.now();
        var info = Gregorian.info(now, Time.FORMAT_SHORT);
        return (info.year * 10000) + (info.month * 100) + info.day;
    }

    // Computes unique integer representation of Sunday starting the current week: YYYYMMDD.
    function getWeekKey() as Number {
        var now = Time.now();
        var info = Gregorian.info(now, Time.FORMAT_SHORT);
        var daysSinceSunday = info.day_of_week - 1;
        var sundayMoment = now.subtract(new Time.Duration(daysSinceSunday * 86400));
        var sundayInfo = Gregorian.info(sundayMoment, Time.FORMAT_SHORT);
        return (sundayInfo.year * 10000) + (sundayInfo.month * 100) + sundayInfo.day;
    }
}

