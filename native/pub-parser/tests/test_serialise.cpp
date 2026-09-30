#include "testing.h"

#include <chrono>
#include <cstdio>
#include <string>

#include "serialise.h"

using namespace pubir;

namespace {

std::string elementId(int n) {
  char buffer[16];
  std::snprintf(buffer, sizeof buffer, "el_%06d", n);
  return buffer;
}

// One page holding `count` plain shapes, listed in the order they were made.
Document documentWith(int count) {
  Document doc;
  Page page;
  page.id = "page_0001";
  for (int n = 0; n < count; n++) {
    Element element;
    element.id = elementId(n);
    element.type = "shape";
    element.zIndex = n;
    page.elementIds.push_back(element.id);
    doc.elements.push_back(std::move(element));
  }
  doc.pages.push_back(std::move(page));
  return doc;
}

} // namespace

TEST(serialise_lists_a_pages_elements_in_its_own_paint_order) {
  Document doc = documentWith(3);
  doc.pages[0].elementIds = {elementId(2), elementId(0), elementId(1)};
  const std::string out = documentJson(doc).dump(2);
  const size_t first = out.find("\"el_000002\"");
  const size_t second = out.find("\"el_000000\"");
  const size_t third = out.find("\"el_000001\"");
  CHECK(first != std::string::npos);
  CHECK(second != std::string::npos);
  CHECK(third != std::string::npos);
  CHECK(first < second);
  CHECK(second < third);
}

TEST(serialise_output_does_not_depend_on_the_order_elements_were_collected) {
  // The page's list decides what is written and in what order, so the same
  // page over the same elements, collected in reverse, writes the same bytes.
  const Document doc = documentWith(50);
  Document reversed = doc;
  reversed.elements.assign(doc.elements.rbegin(), doc.elements.rend());
  CHECK(documentJson(doc).dump(2) == documentJson(reversed).dump(2));
}

TEST(serialise_skips_a_page_entry_naming_no_element) {
  Document doc = documentWith(2);
  doc.pages[0].elementIds = {elementId(0), "el_missing", elementId(1)};
  const std::string out = documentJson(doc).dump(2);
  CHECK(out.find("el_missing") == std::string::npos);
  CHECK(out.find("\"el_000000\"") != std::string::npos);
  CHECK(out.find("\"el_000001\"") != std::string::npos);
}

TEST(serialise_time_grows_linearly_with_the_element_count) {
  // #126: every page entry was found by scanning all elements, about 5e9
  // string comparisons for 100,000 elements -- many seconds, after the
  // collector's own time limit had stopped looking. A lookup built once
  // makes it one pass. The bound is loose enough for a slow runner, and far
  // below what the scan takes.
  const Document doc = documentWith(100000);
  const auto start = std::chrono::steady_clock::now();
  const Json json = documentJson(doc);
  const std::chrono::duration<double> took = std::chrono::steady_clock::now() - start;
  CHECK(!json.isNull());
  CHECK(took.count() < 4.0);
}
