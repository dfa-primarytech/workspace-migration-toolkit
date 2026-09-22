// Resource limits for parsing untrusted input.
//
// A .pub file is an untrusted binary from a retired application. libmspub
// does its own container validation, but a structurally valid file can
// still describe a million elements or a gigabyte of embedded bitmaps. The
// collector checks every limit before it allocates, and when one trips it
// stops accumulating content and records why -- it never throws, because
// unwinding out of a callback through a C++ library's own stack is not
// something libmspub promises to survive.
#ifndef PUBIR_LIMITS_H
#define PUBIR_LIMITS_H

#include <cstddef>

namespace pubir {

struct Limits {
  // Refused before libmspub is handed the stream at all.
  long long maxInputBytes = 64LL * 1024 * 1024;

  long long maxCallbacks = 2000000;
  long long maxPages = 5000;
  long long maxElements = 200000;
  long long maxElementDepth = 64;
  long long maxAssets = 5000;
  long long maxAssetBytes = 64LL * 1024 * 1024;   // per asset
  long long maxTotalAssetBytes = 256LL * 1024 * 1024;
  long long maxTextBytes = 64LL * 1024 * 1024;
  long long maxParagraphsPerContainer = 100000;
  long long maxTableCells = 200000;
  long long maxPathCommands = 100000;
  long long maxPointsPerShape = 100000;
  long long maxDiagnostics = 20000;

  // Wall-clock budget enforced inside the callback sink. This is a
  // backstop, not the real timeout: a hang inside libmspub before it
  // calls back would never reach us. The invoking process must also kill
  // the subprocess -- see docs/publisher-parser.md.
  double maxSeconds = 120.0;
};

} // namespace pubir

#endif
