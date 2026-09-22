// Length conversion to PostScript points.
//
// The IR fixes one length unit for every geometric field so that consumers
// never have to carry a unit alongside a number. Points are the choice
// because Google Slides' API is in points (EMU aside) and because they
// survive A4/A5 page sizes without rounding drift that millimetres cause.
//
// librevenge hands lengths over as doubles tagged with an RVNGUnit; the
// tag is what decides the conversion, never the property name.
#ifndef PUBIR_UNITS_H
#define PUBIR_UNITS_H

#include <librevenge/librevenge.h>

#include <string>

namespace pubir {

struct Length {
  bool valid = false;
  double points = 0.0;
  double sourceValue = 0.0;
  // "in", "pt", "twip", "%", "generic" or "" when unknown.
  std::string sourceUnit;
};

constexpr double kPointsPerInch = 72.0;
constexpr double kPointsPerTwip = 1.0 / 20.0;

double inchesToPoints(double inches);
double twipsToPoints(double twips);
double pointsToInches(double points);

const char *unitName(librevenge::RVNGUnit unit);

// Converts one property to points. A percentage or a unitless generic
// value is not a length: those come back invalid rather than silently
// treated as inches, which is how a 50% fill offset would otherwise turn
// into half an inch.
Length toPoints(const librevenge::RVNGProperty *prop);

// Looks up `name` in `props` and converts it. Missing key -> invalid.
Length lengthProp(const librevenge::RVNGPropertyList &props, const char *name);

} // namespace pubir

#endif
