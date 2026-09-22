#include "testing.h"

#include "json.h"

using namespace pubir;

TEST(json_objects_keep_insertion_order) {
  // Determinism depends on this: a map would sort keys and two builds of
  // the same document would differ only in field order.
  Json object = Json::object();
  object.set("zebra", Json::integer(1));
  object.set("alpha", Json::integer(2));
  CHECK_EQ(object.dump(0), std::string("{\"zebra\":1,\"alpha\":2}"));
}

TEST(json_resetting_a_key_keeps_its_position) {
  Json object = Json::object();
  object.set("a", Json::integer(1));
  object.set("b", Json::integer(2));
  object.set("a", Json::integer(3));
  CHECK_EQ(object.dump(0), std::string("{\"a\":3,\"b\":2}"));
}

TEST(json_formats_integral_doubles_without_a_point) {
  CHECK_EQ(Json::formatDouble(72.0), std::string("72"));
  CHECK_EQ(Json::formatDouble(-36.0), std::string("-36"));
}

TEST(json_trims_trailing_zeros) {
  CHECK_EQ(Json::formatDouble(420.945), std::string("420.945"));
  CHECK_EQ(Json::formatDouble(0.5), std::string("0.5"));
}

TEST(json_negative_zero_prints_as_zero) {
  // Two runs that compute 0 by different routes must produce the same byte.
  CHECK_EQ(Json::formatDouble(-0.0), std::string("0"));
  CHECK_EQ(Json::formatDouble(0.0), std::string("0"));
}

TEST(json_escapes_control_characters_and_quotes) {
  CHECK_EQ(Json::escape("a\"b\\c"), std::string("a\\\"b\\\\c"));
  CHECK_EQ(Json::escape("a\nb\tc"), std::string("a\\nb\\tc"));
  CHECK_EQ(Json::escape(std::string("a\x01" "b")), std::string("a\\u0001b"));
}

TEST(json_passes_utf8_through_unchanged) {
  // librevenge hands over UTF-8; re-encoding it here would corrupt any
  // document with a curly apostrophe in it.
  const std::string utf8 = "caf\xc3\xa9";
  CHECK_EQ(Json::escape(utf8), utf8);
}

TEST(json_non_finite_numbers_become_null) {
  CHECK(Json::number(1.0 / 0.0).isNull());
  CHECK(Json::number(0.0 / 0.0).isNull());
}

TEST(json_empty_containers_are_compact) {
  CHECK_EQ(Json::array().dump(0), std::string("[]"));
  CHECK_EQ(Json::object().dump(0), std::string("{}"));
}

TEST(json_nested_pretty_printing_is_stable) {
  Json root = Json::object();
  Json list = Json::array();
  list.push(Json::string("x"));
  root.set("items", std::move(list));
  CHECK_EQ(root.dump(2), std::string("{\n  \"items\": [\n    \"x\"\n  ]\n}\n"));
}
