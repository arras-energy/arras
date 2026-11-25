#include "climate.h"
#include <stdio.h>
int main() {
  SolarAngles sa;
  short days[] = {1, 80, 172, 266, 355};
  double lats[] = {0.8, -0.6, 0.1};
  for (short d : days) for (double lat : lats) {
    double st = sa.solar_time(10.5, d, -2.0943951, -2.1);
    printf("%d %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g\n", d, lat, sa.eq_time(d), sa.declination(d), st,
      sa.cos_incident(lat, 0.5, 0.3, st, d), sa.zenith(d, lat, st), sa.altitude(d, lat, st), sa.elevation(d, lat, st), sa.azimuth(d, lat, st),
      sa.hr_sunrise(d, lat), sa.day_len(d, lat));
  }
  // solpos cases
  int hours[] = {6, 9, 12, 15, 19};
  for (int h : hours) {
    sa.S_init(&sa.solpos_vals);
    sa.solpos_vals.longitude = -120.55; sa.solpos_vals.latitude = 46.5667*PI/180; sa.solpos_vals.timezone = -8;
    sa.solpos_vals.year = 2006; sa.solpos_vals.daynum = 121 + h; sa.solpos_vals.hour = h; sa.solpos_vals.minute = 30; sa.solpos_vals.second = 0;
    sa.solpos_vals.temp = 12.0; sa.solpos_vals.press = 980; sa.solpos_vals.solcon = 125.0;
    sa.solpos_vals.aspect = 3.3; sa.solpos_vals.tilt = 0.5; sa.solpos_vals.diff_horz = (h==19?0:8.0); sa.solpos_vals.dir_norm = (h==12?60.0:(h==6?0:30.0));
    sa.S_solpos(&sa.solpos_vals);
    SolarAngles::SOLPOS_POSDATA &p = sa.solpos_vals;
    printf("solpos %d %d %d %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %d\n", h, p.month, p.day, p.azim, p.zenref, p.cosinc, p.etrn, p.etr, p.amass, p.sretr, p.ssetr, p.perez_horz, p.sbcf, p.eqntim, p.perez_F1, p.perez_skyclear_idx);
  }
}
