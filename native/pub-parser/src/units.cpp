#include "units.h"

namespace pubir {

double inchesToPoints(double inches) { return inches * kPointsPerInch; }
double twipsToPoints(double twips) { return twips * kPointsPerTwip; }
double pointsToInches(double points) { return points / kPointsPerInch; }

const char *unitName(librevenge::RVNGUnit unit) {
  switch (unit) {
  case librevenge::RVNG_INCH: return "in";
  case librevenge::RVNG_POINT: return "pt";
  case librevenge::RVNG_TWIP: return "twip";
  case librevenge::RVNG_PERCENT: return "%";
  case librevenge::RVNG_GENERIC: return "generic";
  case librevenge::RVNG_UNIT_ERROR: return "";
  }
  return "";
}

Length toPoints(const librevenge::RVNGProperty *prop) {
  Length out;
  if (prop == nullptr) return out;

  const librevenge::RVNGUnit unit = prop->getUnit();
  out.sourceValue = prop->getDouble();
  out.sourceUnit = unitName(unit);

  switch (unit) {
  case librevenge::RVNG_INCH:
    out.points = inchesToPoints(out.sourceValue);
    out.valid = true;
    break;
  case librevenge::RVNG_POINT:
    out.points = out.sourceValue;
    out.valid = true;
    break;
  case librevenge::RVNG_TWIP:
    out.points = twipsToPoints(out.sourceValue);
    out.valid = true;
    break;
  case librevenge::RVNG_PERCENT:
  case librevenge::RVNG_GENERIC:
  case librevenge::RVNG_UNIT_ERROR:
    // Not a length. The raw value still reaches the IR through
    // sourceProperties, so nothing is lost by refusing to convert it.
    break;
  }
  return out;
}

Length lengthProp(const librevenge::RVNGPropertyList &props, const char *name) {
  return toPoints(props[name]);
}

} // namespace pubir
