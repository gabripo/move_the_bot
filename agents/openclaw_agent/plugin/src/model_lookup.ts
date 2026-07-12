import * as fs from "fs";
import * as path from "path";
import * as crypto from "crypto";

const BUILTIN_INDEX_PATH = path.join(process.cwd(), "..", "..", "..", "models", "builtin", "index.json");
const CACHE_DIR = process.env.MODEL_CACHE_DIR || path.join(process.cwd(), "..", "..", "..", "models", "cache");

interface BuiltinIndex {
  [key: string]: string;
}

let builtinIndex: BuiltinIndex | null = null;

function loadBuiltinIndex(): BuiltinIndex {
  if (!builtinIndex) {
    const raw = fs.readFileSync(BUILTIN_INDEX_PATH, "utf-8");
    builtinIndex = JSON.parse(raw);
  }
  return builtinIndex;
}

export async function lookupModel(objectName: string): Promise<string | null> {
  const name = objectName.trim().toLowerCase();
  if (!name) return null;

  // 1. Builtin
  const index = loadBuiltinIndex();
  if (name in index) {
    const modelPath = path.join(
      path.dirname(BUILTIN_INDEX_PATH),
      index[name]
    );
    if (fs.existsSync(modelPath)) {
      return modelPath;
    }
  }

  // 2. Cache
  const cacheKey = crypto.createHash("md5").update(name).digest("hex");
  for (const ext of [".glb", ".gltf"]) {
    const cached = path.join(CACHE_DIR, `${cacheKey}${ext}`);
    if (fs.existsSync(cached)) {
      return cached;
    }
  }

  // 3. Sketchfab fallback (would be called from Python side via rosbridge)
  // Sketchfab download is handled by the Python model_lookup module.
  // The spawn_object tool should call Python bridge if needed.
  return null;
}
