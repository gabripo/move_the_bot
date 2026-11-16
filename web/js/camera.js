// Opens the computer's own webcam. Without a device named, browsers take the first camera the
// system lists, which can be a virtual one (OBS Virtual Camera, Snap Camera…) that only shows
// black while its app is closed. ?camera=NAME picks a camera whose name contains NAME.

const VIRTUAL = /virtual|obs|snap camera|mmhmm|ndi|camo|elgato|droidcam/i;

async function pick(size) {
  const wanted = new URLSearchParams(location.search).get("camera");
  const cameras = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
  if (!cameras.length || !cameras[0].label) return null;   // names are known only after a first permission
  const choice = wanted
    ? cameras.find((c) => c.label.toLowerCase().includes(wanted.toLowerCase()))
    : cameras.find((c) => !VIRTUAL.test(c.label));
  return choice ? { ...size, deviceId: { exact: choice.deviceId } } : null;
}

export async function openCamera(size) {
  let video = (await pick(size).catch(() => null)) || { ...size, facingMode: "user" };
  let stream = await navigator.mediaDevices.getUserMedia({ video });
  // The very first time, names were unknown: if that gave a virtual camera, switch.
  const label = stream.getVideoTracks()[0]?.label || "";
  if (VIRTUAL.test(label) && !new URLSearchParams(location.search).get("camera")) {
    const better = await pick(size).catch(() => null);
    if (better) {
      stream.getTracks().forEach((t) => t.stop());
      stream = await navigator.mediaDevices.getUserMedia({ video: better });
    }
  }
  return stream;
}
