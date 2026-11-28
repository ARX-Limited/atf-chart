"""TARGET publication days for the EUR leg of the matched benchmark chart."""
import sys
from datetime import date, timedelta


def easter_sunday(year):
    # Gregorian computus (Meeus/Jones/Butcher).
    century, year_in_century = divmod(year, 100)
    golden = year % 19
    correction = (century - (century + 8) // 25 + 1) // 3
    epact = (19 * golden + century - century // 4 - correction + 15) % 30
    offset = (32 + 2 * (century % 4) + 2 * (year_in_century // 4)
              - epact - year_in_century % 4) % 7
    leap = (golden + 11 * epact + 22 * offset) // 451
    month, day = divmod(epact + offset - 7 * leap + 114, 31)
    return date(year, month, day + 1)


def is_business_day(day):
    easter = easter_sunday(day.year)
    return (day.weekday() < 5
            and (day.month, day.day) not in {(1, 1), (5, 1), (12, 25), (12, 26)}
            and day not in (easter - timedelta(days=2), easter + timedelta(days=1)))


if __name__ == "__main__":
    print("true" if is_business_day(date.fromisoformat(sys.argv[1])) else "false")
