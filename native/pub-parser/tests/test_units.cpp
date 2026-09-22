#include "testing.h"

#include <librevenge/librevenge.h>

#include "units.h"

using namespace pubir;

namespace {

Length convert(const char *key, double value, librevenge::RVNGUnit unit) {
  librevenge::RVNGPropertyList props;
  props.insert(key, value, unit);
  return lengthProp(props, key);
}

} // namespace

TEST(units_inches_convert_to_points) {
  const Length length = convert("svg:width", 1.0, librevenge::RVNG_INCH);
  CHECK(length.valid);
  CHECK_NEAR(length.points, 72.0, 1e-9);
  CHECK_EQ(length.sourceUnit, std::string("in"));
  CHECK_NEAR(length.sourceValue, 1.0, 1e-9);
}

TEST(units_a5_page_size_round_trips) {
  // A5 portrait, the page size the first real fixture is expected to use.
  // 148 x 210 mm is 5.8268 x 8.2677 in, which is what has to come out as
  // roughly 420.9 x 595.3 pt.
  const Length width = convert("svg:width", 5.8268, librevenge::RVNG_INCH);
  const Length height = convert("svg:height", 8.2677, librevenge::RVNG_INCH);
  CHECK_NEAR(width.points, 419.53, 0.5);
  CHECK_NEAR(height.points, 595.27, 0.5);
}

TEST(units_points_pass_through) {
  const Length length = convert("fo:font-size", 18.0, librevenge::RVNG_POINT);
  CHECK(length.valid);
  CHECK_NEAR(length.points, 18.0, 1e-9);
  CHECK_EQ(length.sourceUnit, std::string("pt"));
}

TEST(units_twips_convert_to_points) {
  const Length length = convert("svg:x", 1440.0, librevenge::RVNG_TWIP);
  CHECK(length.valid);
  CHECK_NEAR(length.points, 72.0, 1e-9);
}

TEST(units_percent_is_not_a_length) {
  // The trap this exists to catch: librevenge stores a percentage as a
  // fraction, so treating it as inches turns a 50% offset into half an
  // inch. It must come back invalid instead.
  const Length length = convert("draw:opacity", 0.5, librevenge::RVNG_PERCENT);
  CHECK(!length.valid);
  CHECK_EQ(length.sourceUnit, std::string("%"));
}

TEST(units_generic_is_not_a_length) {
  const Length length = convert("librevenge:rotate", 45.0, librevenge::RVNG_GENERIC);
  CHECK(!length.valid);
}

TEST(units_missing_property_is_invalid) {
  librevenge::RVNGPropertyList props;
  CHECK(!lengthProp(props, "svg:width").valid);
  CHECK(!toPoints(nullptr).valid);
}

TEST(units_negative_values_convert) {
  const Length length = convert("svg:x", -0.5, librevenge::RVNG_INCH);
  CHECK(length.valid);
  CHECK_NEAR(length.points, -36.0, 1e-9);
}
