// publisher-parser: .pub -> intermediate representation.
//
//   publisher-parser input.pub output/
//
// Produces output/document.json, output/assets.json, output/report.json and
// output/assets/<sha256>.<ext>.
//
// The bundle is the deliverable and is deliberately kept. Scratch files are
// not: see bundle.cpp.
#include <libmspub/libmspub.h>
#include <librevenge-stream/librevenge-stream.h>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <fstream>
#include <memory>
#include <new>
#include <stdexcept>
#include <string>
#include <vector>

#include "bundle.h"
#include "collector.h"
#include "limits.h"
#include "model.h"
#include "serialise.h"
#include "sha256.h"

namespace {

// OLE2 compound file magic. Publisher files are OLE containers; libmspub
// does the real validation, but recognising the container cheaply lets the
// report say what the file actually was when parsing fails.
const unsigned char kOle2Magic[8] = {0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1};

void usage() {
  std::fprintf(stderr,
               "usage: publisher-parser [options] <input.pub> <output-directory>\n"
               "\n"
               "Options:\n"
               "  --force                 write into a non-empty output directory\n"
               "  --max-input-bytes N     refuse inputs larger than N bytes\n"
               "  --max-seconds S         collection time budget (a backstop; the caller must\n"
               "                          also impose a hard subprocess timeout)\n"
               "  --max-callbacks N       maximum collected callbacks\n"
               "  --max-pages N           maximum collected pages\n"
               "  --max-elements N        maximum collected elements\n"
               "  --max-assets N          maximum distinct extracted assets\n"
               "  --max-asset-bytes N     maximum bytes for a single asset\n"
               "  --max-total-asset-bytes N  maximum bytes across all assets\n"
               "  --max-text-bytes N      maximum collected text bytes\n"
               "  --version               print the parser and library versions\n"
               "  --help                  print this message\n");
}

// Splits on both separators on every platform, so a Windows path such as
// C:\Users\<name>\booklet.pub never reaches the bundle whole.
std::string basename(const std::string &path) {
  const std::size_t slash = path.find_last_of("/\\");
  return slash == std::string::npos ? path : path.substr(slash + 1);
}

bool parseLongLong(const char *text, long long &out) {
  if (text == nullptr || *text == '\0') return false;
  char *end = nullptr;
  const long long value = std::strtoll(text, &end, 10);
  if (end == nullptr || *end != '\0' || value <= 0) return false;
  out = value;
  return true;
}

// Writes a bundle for an input that never reached a model, so a caller
// always has a machine-readable answer rather than only an exit code.
int failEarly(const pubir::Document &doc, const pubir::Limits &limits,
              const std::string &outputDir, bool force, const char *code, const char *message) {
  // The message is a fixed string chosen here, never anything read out of
  // the document, so a hostile file cannot write its own text into a log.
  std::fprintf(stderr, "publisher-parser: %s: %s\n", code, message);
  const pubir::WriteResult written =
      pubir::writeBundle(doc, limits, outputDir, "failed", force, code, message);
  if (!written.ok) {
    std::fprintf(stderr, "publisher-parser: %s: %s\n", written.errorCode.c_str(),
                 written.errorMessage.c_str());
  }
  return 2;
}

// Exit status when the parser itself failed (an exception escaped), as
// opposed to refusing its input (2) or failing to parse it (1).
constexpr int kInternalFailure = 4;

// The output directory as given on the command line: argv's own storage, so
// the last-resort path below can use it without allocating.
const char *gOutputDir = nullptr;

// The last resort when an exception reaches main (#129). It may run because
// memory ran out, so it allocates nothing: a fixed line on stderr, then at
// most a short report.json built in stack buffers, the one field the app
// reads (failureCode) included. Best effort only -- if the directory cannot
// be made or the file already exists, the exit status alone says it failed.
void lastResortReport(const char *code, const char *message) {
  std::fprintf(stderr, "publisher-parser: %s: %s\n", code, message);
  if (gOutputDir == nullptr) return;
  ::mkdir(gOutputDir, 0700);
  char path[4096];
  const int pathLength = std::snprintf(path, sizeof path, "%s/report.json", gOutputDir);
  if (pathLength < 0 || static_cast<std::size_t>(pathLength) >= sizeof path) return;
  // O_EXCL: never overwrite a report, or anything, that is already there.
  const int fd = ::open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
  if (fd < 0) return;
  char body[512];
  const int bodyLength = std::snprintf(
      body, sizeof body,
      "{\"schemaVersion\": \"%s\", \"status\": \"failed\", \"failureCode\": \"%s\", "
      "\"failureMessage\": \"%s\"}\n",
      pubir::kSchemaVersion, code, message);
  if (bodyLength > 0 && static_cast<std::size_t>(bodyLength) < sizeof body) {
    const ssize_t written = ::write(fd, body, static_cast<std::size_t>(bodyLength));
    (void)written;
  }
  ::close(fd);
}

// Lets a test make the parser throw once it has read its input, standing in
// for an allocation that fails on a large document, which cannot be produced
// on demand. Unset in normal use; the variable is read, never the document.
void failForTesting() {
  const char *failure = std::getenv("PUBIR_FAIL_FOR_TESTING");
  if (failure == nullptr) return;
  if (std::strcmp(failure, "bad-alloc") == 0) throw std::bad_alloc();
  if (std::strcmp(failure, "exception") == 0) throw std::runtime_error("injected for testing");
}

int run(int argc, char **argv);

} // namespace

int main(int argc, char **argv) {
  // Without this, an escaping exception -- std::bad_alloc from a large but
  // within-limit document most plausibly -- ended in std::terminate: an
  // abort, no report, and a signal where the app expects an exit status.
  try {
    return run(argc, argv);
  } catch (const std::bad_alloc &) {
    lastResortReport("out-of-memory", "the parser ran out of memory");
  } catch (...) {
    lastResortReport("internal-error", "the parser stopped on an unexpected internal error");
  }
  return kInternalFailure;
}

namespace {

int run(int argc, char **argv) {
  pubir::Limits limits;
  bool force = false;
  std::vector<std::string> positional;

  for (int i = 1; i < argc; i++) {
    const std::string arg(argv[i]);
    if (arg == "--help" || arg == "-h") {
      usage();
      return 0;
    }
    if (arg == "--version") {
      std::printf("%s %s\n", pubir::kGeneratorName, pubir::kGeneratorVersion);
      std::printf("schema %s\n", pubir::kSchemaVersion);
        // libmspub and librevenge expose no version macro, so the versions
      // the binary was built against are baked in by CMake from pkg-config.
      std::printf("libmspub %s%s%s\n", PUBIR_LIBMSPUB_VERSION,
                  PUBIR_LIBMSPUB_PATCHES[0] ? " patched: " : "", PUBIR_LIBMSPUB_PATCHES);
      std::printf("librevenge %s\n", PUBIR_LIBREVENGE_VERSION);
      return 0;
    }
    if (arg == "--force") {
      force = true;
      continue;
    }

    auto needsValue = [&](const char *name, long long &target) -> bool {
      if (arg != name) return false;
      if (i + 1 >= argc || !parseLongLong(argv[i + 1], target)) {
        std::fprintf(stderr, "publisher-parser: %s needs a positive integer\n", name);
        std::exit(2);
      }
      i++;
      return true;
    };
    if (needsValue("--max-input-bytes", limits.maxInputBytes)) continue;
    if (needsValue("--max-callbacks", limits.maxCallbacks)) continue;
    if (needsValue("--max-pages", limits.maxPages)) continue;
    if (needsValue("--max-elements", limits.maxElements)) continue;
    if (needsValue("--max-assets", limits.maxAssets)) continue;
    if (needsValue("--max-asset-bytes", limits.maxAssetBytes)) continue;
    if (needsValue("--max-total-asset-bytes", limits.maxTotalAssetBytes)) continue;
    if (needsValue("--max-text-bytes", limits.maxTextBytes)) continue;
    if (arg == "--max-seconds") {
      long long seconds = 0;
      if (i + 1 >= argc || !parseLongLong(argv[i + 1], seconds)) {
        std::fprintf(stderr, "publisher-parser: --max-seconds needs a positive integer\n");
        return 2;
      }
      limits.maxSeconds = static_cast<double>(seconds);
      i++;
      continue;
    }
    if (!arg.empty() && arg[0] == '-') {
      std::fprintf(stderr, "publisher-parser: unknown option %s\n", arg.c_str());
      usage();
      return 2;
    }
    positional.push_back(arg);
    if (positional.size() == 2) gOutputDir = argv[i];
  }

  if (positional.size() != 2) {
    usage();
    return 2;
  }
  const std::string inputPath = positional[0];
  const std::string outputDir = positional[1];

  pubir::Document doc;
  // Only the basename reaches the bundle. The directory a file was
  // processed in is often a person's name on a school machine, and the
  // bundle is meant to be shareable with whoever reviews the conversion.
  doc.sourceFilename = basename(inputPath);

  std::ifstream input(inputPath, std::ios::binary | std::ios::ate);
  if (!input) {
    return failEarly(doc, limits, outputDir, force, "input-unreadable",
                     "the input file could not be opened");
  }
  const std::streamoff size = input.tellg();
  if (size < 0) {
    return failEarly(doc, limits, outputDir, force, "input-unreadable",
                     "the input file size could not be determined");
  }
  if (static_cast<long long>(size) > limits.maxInputBytes) {
    doc.sourceByteLength = static_cast<long long>(size);
    return failEarly(doc, limits, outputDir, force, "input-too-large",
                     "the input file is larger than the configured limit");
  }
  if (size == 0) {
    return failEarly(doc, limits, outputDir, force, "input-empty", "the input file is empty");
  }

  std::string bytes;
  bytes.resize(static_cast<std::size_t>(size));
  input.seekg(0);
  input.read(&bytes[0], size);
  if (!input) {
    return failEarly(doc, limits, outputDir, force, "input-unreadable",
                     "the input file could not be read in full");
  }
  input.close();
  failForTesting();

  doc.sourceByteLength = static_cast<long long>(bytes.size());
  doc.sourceSha256 = pubir::Sha256::of(bytes);
  doc.containerType = (bytes.size() >= sizeof(kOle2Magic) &&
                       std::memcmp(bytes.data(), kOle2Magic, sizeof(kOle2Magic)) == 0)
                          ? "ole2"
                          : "unknown";

  librevenge::RVNGStringStream stream(reinterpret_cast<const unsigned char *>(bytes.data()),
                                      static_cast<unsigned int>(bytes.size()));

  // Container validation is libmspub's job, not ours: it walks the OLE
  // directory and the Publisher streams. Anything it refuses, we refuse.
  if (!libmspub::MSPUBDocument::isSupported(&stream)) {
    doc.supportedByParser = false;
    return failEarly(doc, limits, outputDir, force, "unsupported-document",
                     "libmspub does not recognise this file as a Publisher document");
  }
  doc.supportedByParser = true;
  // libmspub's public API exposes no version accessor, so the family is as
  // specific as this parser can honestly be.
  doc.formatFamily = "microsoft-publisher";

  pubir::IrCollector collector(limits);
  collector.setSource(doc.sourceFilename, doc.sourceSha256, doc.sourceByteLength, doc.containerType,
                      doc.formatFamily);
  collector.setSupported(true);

  stream.seek(0, librevenge::RVNG_SEEK_SET);
  const bool parsed = libmspub::MSPUBDocument::parse(&stream, &collector);
  const pubir::Document &model = collector.finish();

  if (!parsed) {
    const pubir::WriteResult written =
        pubir::writeBundle(model, limits, outputDir, "failed", force, "parse-failed",
                           "libmspub reported a parse failure; any content collected before the "
                           "failure is included in this bundle");
    if (!written.ok) {
      std::fprintf(stderr, "publisher-parser: %s: %s\n", written.errorCode.c_str(),
                   written.errorMessage.c_str());
      return 2;
    }
    std::fprintf(stderr, "publisher-parser: parse-failed: libmspub could not parse this document\n");
    return 1;
  }

  // libmspub reads each picture's crop from the drawing records and drops
  // it, so a cropped picture would be drawn whole, stretched into its frame.
  // Keep the records as they are: the app reads the crops from them. They
  // come from the same OLE container libmspub has just accepted, through
  // librevenge, and are held to the per-asset size limit.
  // The stored pictures are kept too (Escher/EscherDelayStm): libmspub takes
  // from them only the pictures it places, and leaves those set inline in
  // text. They are held to the limit on all assets together.
  const auto substream = [&stream](const char *name, long long limit) {
    std::string data;
    stream.seek(0, librevenge::RVNG_SEEK_SET);
    std::unique_ptr<librevenge::RVNGInputStream> sub(
        stream.isStructured() ? stream.getSubStreamByName(name) : nullptr);
    if (!sub) return data;
    while (!sub->isEnd() && static_cast<long long>(data.size()) <= limit) {
      unsigned long got = 0;
      const unsigned char *chunk = sub->read(64 * 1024, got);
      if (chunk == nullptr || got == 0) break;
      data.append(reinterpret_cast<const char *>(chunk), got);
    }
    if (static_cast<long long>(data.size()) > limit) data.clear();
    return data;
  };
  std::string drawing = substream("Escher/EscherStm", limits.maxAssetBytes);
  if (!drawing.empty()) collector.setDrawingData(std::move(drawing));
  std::string pictures = substream("Escher/EscherDelayStm", limits.maxTotalAssetBytes);
  if (!pictures.empty()) collector.setDrawingDelayData(std::move(pictures));

  const std::string status = model.truncated ? "truncated" : "ok";
  const pubir::WriteResult written = pubir::writeBundle(model, limits, outputDir, status, force);
  if (!written.ok) {
    std::fprintf(stderr, "publisher-parser: %s: %s\n", written.errorCode.c_str(),
                 written.errorMessage.c_str());
    return 2;
  }

  // Counts only. Nothing from the document's text or images is ever
  // printed: this output goes to logs.
  std::printf("pages=%lld elements=%lld assets=%lld fonts=%lld callbacks=%lld status=%s\n",
              model.counts.pages, model.counts.elements, model.counts.assets, model.counts.fonts,
              model.callbackTotal, status.c_str());
  return model.truncated ? 3 : 0;
}

} // namespace
