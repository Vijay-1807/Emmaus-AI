/**
 * Downscale large photos before upload. A 21MB phone photo becomes ~300KB,
 * which fixes Cloudinary's 10MB reject and the giant base64 vision payloads
 * that crash cloud vision gateways. Small images pass through untouched.
 */
export async function maybeCompressImage(
  file: File,
  maxDim = 1920,
  quality = 0.85,
): Promise<File> {
  if (!file.type.startsWith("image/")) return file;
  if (file.size <= 2 * 1024 * 1024) return file;
  try {
    if (typeof createImageBitmap === "undefined") return file;
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxDim / Math.max(bitmap.width, bitmap.height));
    if (scale >= 1) {
      bitmap.close();
      return file;
    }
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      bitmap.close();
      return file;
    }
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", quality),
    );
    if (!blob) return file;
    const name = file.name.replace(/\.(png|webp|bmp|heic|heif|tiff?)$/i, ".jpg");
    return new File([blob], name, { type: "image/jpeg" });
  } catch {
    return file;
  }
}
