const BACKEND_URL = "https://driver-guard-ai-production.up.railway.app";

const cameraImg = document.querySelector(".camera-stream");

let webcamStream = null;
let analyzeTimer = null;
let previewAnimationId = null;
let latestAI = null;

const videoElement = document.createElement("video");
videoElement.autoplay = true;
videoElement.playsInline = true;
videoElement.muted = true;

const previewCanvas = document.createElement("canvas");
const previewCtx = previewCanvas.getContext("2d");

const analyzeCanvas = document.createElement("canvas");
const analyzeCtx = analyzeCanvas.getContext("2d");

let aiLogEntries = [];
let currentRecognizedDriverId = null;

function textOrDash(value) {
    return value || "--";
}

function getInitials(name) {
    if (!name || name === "Không xác định" || name === "Đang chờ nhận diện") return "--";
    return name.trim().split(/\s+/).slice(-2).map(p => p[0]).join("").toUpperCase();
}

const CANVAS_WIDTH = 960;
const CANVAS_HEIGHT = 360;
const HALF_WIDTH = 480;

const AI_STATUS_MAP = {
    "EYES OPEN": { text: "Mở", css: "status-success" },
    "EYES CLOSED": { text: "Nhắm", css: "status-danger" },
    "NO FACE": { text: "--", css: "" },
    "NORMAL": { text: "Bình thường", css: "status-success" },
    "MOUTH OPEN": { text: "Mở", css: "status-warning" },
    "YAWNING": { text: "Ngáp", css: "status-danger" },
    "HEAD DOWN": { text: "Cúi", css: "status-danger" }
};

const DROWSY_LEVEL_MAP = {
    "NORMAL": { text: "Thấp", css: "status-success" },
    "TIRED": { text: "Trung bình", css: "status-warning" },
    "DROWSY": { text: "Cao", css: "status-danger" },
    "HEAD DOWN ALERT": { text: "Cao", css: "status-danger" }
};

function setBadge(element, text, className) {
    if (!element) return;
    element.textContent = text;
    element.className = `badge ${className}`;
}

function setStatusBox(id, mapped) {
    const box = document.getElementById(id);
    if (!box) return;

    const strong = box.querySelector("strong");
    if (strong) strong.textContent = mapped.text;

    box.className = "status-box " + mapped.css;
}

function createLogItem(title, detail) {
    const item = document.createElement("div");
    item.className = "log-item";

    const strong = document.createElement("strong");
    strong.textContent = title;

    const time = document.createElement("div");
    time.className = "log-time";
    time.textContent = detail;

    item.appendChild(strong);
    item.appendChild(time);

    return item;
}

function renderAILog() {
    const logList = document.getElementById("aiLogList");
    if (!logList) return;

    logList.replaceChildren();

    if (aiLogEntries.length === 0) {
        logList.appendChild(createLogItem("Chưa có dữ liệu", "Bắt đầu camera để theo dõi"));
        return;
    }

    for (const entry of aiLogEntries) {
        logList.appendChild(createLogItem(entry.title, entry.detail));
    }
}

function updateAIStatus(ai) {
    if (!ai) return;

    const eye = AI_STATUS_MAP[ai.eye_status] || AI_STATUS_MAP["NO FACE"];
    const mouth = AI_STATUS_MAP[ai.mouth_status] || AI_STATUS_MAP["NORMAL"];
    const head = AI_STATUS_MAP[ai.head_status] || AI_STATUS_MAP["NORMAL"];
    const level = DROWSY_LEVEL_MAP[ai.drowsy_status] || DROWSY_LEVEL_MAP["NORMAL"];

    setStatusBox("aiEyeStatus", eye);
    setStatusBox("aiMouthStatus", mouth);
    setStatusBox("aiHeadStatus", head);
    setStatusBox("aiAlertLevel", level);

    const now = new Date().toLocaleTimeString("vi-VN", { hour12: false });
    let newEntry = null;

    if (ai.eye_status === "EYES CLOSED") {
        newEntry = {
            title: "Phát hiện nhắm mắt",
            detail: `${now} - EAR: ${ai.ear ?? "--"}`
        };
    } else if (ai.mouth_status === "MOUTH OPEN" || ai.mouth_status === "YAWNING") {
        newEntry = {
            title: "Phát hiện mở miệng / ngáp",
            detail: `${now} - MAR: ${ai.mar ?? "--"}`
        };
    } else if (ai.head_status === "HEAD DOWN") {
        newEntry = {
            title: "Phát hiện cúi đầu",
            detail: `${now} - Đầu cúi xuống`
        };
    } else if (ai.drowsy_status === "DROWSY" || ai.drowsy_status === "TIRED") {
        newEntry = {
            title: "Cảnh báo buồn ngủ",
            detail: `${now} - ${ai.drowsy_status}`
        };
    }

    if (newEntry) {
        const last = aiLogEntries[0];
        if (!last || last.title !== newEntry.title) {
            aiLogEntries.unshift(newEntry);
            if (aiLogEntries.length > 10) aiLogEntries.length = 10;
            renderAILog();
        }
    }
}

function updateCameraPanel(ai, recognition) {
    updateAIStatus(ai);

    const driverName = document.getElementById("cameraDriverName");
    const driverAvatar = document.getElementById("cameraDriverAvatar");
    const driverVerify = document.getElementById("cameraDriverVerify");
    const vehiclePlate = document.getElementById("cameraVehiclePlate");
    const shiftInfo = document.getElementById("cameraShiftInfo");
    const driverPhone = document.getElementById("cameraDriverPhone");
    const recognitionBadge = document.getElementById("cameraRecognitionBadge");
    const driverChip = document.getElementById("cameraDriverChip");
    const confidenceChip = document.getElementById("cameraConfidenceChip");
    const vehicleChip = document.getElementById("cameraVehicleChip");
    const statusChip = document.getElementById("cameraStatusChip");
    const enrollFaceButton = document.getElementById("enrollFaceButton");

    // Cập nhật chip EAR/MAR luôn hiển thị dữ liệu AI realtime
    if (confidenceChip) {
        confidenceChip.textContent = `EAR: ${ai.ear ?? "--"} | MAR: ${ai.mar ?? "--"}`;
    }
    if (statusChip) {
        statusChip.textContent = `Trạng thái: ${ai.drowsy_status || "NORMAL"}`;
        statusChip.classList.toggle("danger", ai.drowsy_status && ai.drowsy_status !== "NORMAL");
    }

    if (!recognition) return;

    if (recognition.status === "RECOGNIZED") {
        currentRecognizedDriverId = recognition.driver_id;
        if (enrollFaceButton) enrollFaceButton.disabled = false;

        if (driverName) driverName.textContent = recognition.driver_name;
        if (driverAvatar) driverAvatar.textContent = getInitials(recognition.driver_name);
        if (driverVerify) driverVerify.textContent = `Đã xác thực khuôn mặt - độ chính xác ${recognition.confidence}%`;
        if (vehiclePlate) vehiclePlate.textContent = textOrDash(recognition.vehicle_plate);
        if (shiftInfo) shiftInfo.textContent = `${textOrDash(recognition.shift_name)} | ${textOrDash(recognition.shift_time)}`;
        if (driverPhone) driverPhone.textContent = textOrDash(recognition.phone);
        setBadge(recognitionBadge, "Đã xác thực", "badge-success");
        if (driverChip) driverChip.textContent = `Tài xế: ${recognition.driver_name}`;
        if (vehicleChip) vehicleChip.textContent = `Xe: ${textOrDash(recognition.vehicle_plate)}`;
        return;
    }

    if (recognition.status === "UNKNOWN_DRIVER") {
        currentRecognizedDriverId = null;
        if (enrollFaceButton) enrollFaceButton.disabled = true;

        if (driverName) driverName.textContent = "Không xác định";
        if (driverAvatar) driverAvatar.textContent = "??";
        if (driverVerify) driverVerify.textContent = `Không khớp dữ liệu tài xế - độ gần nhất ${recognition.confidence}%`;
        if (vehiclePlate) vehiclePlate.textContent = "--";
        if (shiftInfo) shiftInfo.textContent = "--";
        if (driverPhone) driverPhone.textContent = "--";
        setBadge(recognitionBadge, "Không xác định", "badge-danger");
        if (driverChip) driverChip.textContent = "Tài xế: Không xác định";
        if (vehicleChip) vehicleChip.textContent = "Xe: --";
        return;
    }

    // NO_FACE hoặc chưa nhận diện
    currentRecognizedDriverId = null;
    if (enrollFaceButton) enrollFaceButton.disabled = true;

    if (driverName) driverName.textContent = "Đang chờ nhận diện";
    if (driverAvatar) driverAvatar.textContent = "--";
    if (driverVerify) driverVerify.textContent = "Camera chưa xác thực tài xế";
    if (vehiclePlate) vehiclePlate.textContent = "--";
    if (shiftInfo) shiftInfo.textContent = "--";
    if (driverPhone) driverPhone.textContent = "--";
    setBadge(recognitionBadge, "Đang chờ", "badge-warning");
    if (driverChip) driverChip.textContent = "Tài xế: Đang chờ";
    if (vehicleChip) vehicleChip.textContent = "Xe: --";
}

async function enrollRecognizedFace() {
    if (!currentRecognizedDriverId) {
        alert("Camera chưa xác thực tài xế");
        return;
    }

    const enrollFaceButton = document.getElementById("enrollFaceButton");
    if (enrollFaceButton) {
        enrollFaceButton.disabled = true;
        enrollFaceButton.textContent = "Đang ghi...";
    }

    // Chụp frame hiện tại từ canvas đang dùng để phân tích
    const imageBase64 = analyzeCanvas.toDataURL("image/jpeg", 0.9);

    try {
        const response = await fetch(`${BACKEND_URL}/drivers/${currentRecognizedDriverId}/enroll_face_from_camera`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ image: imageBase64 }),
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Không thể ghi mẫu khuôn mặt");
        alert(data.message || "Đã ghi mẫu khuôn mặt");
    } catch (error) {
        console.error("Lỗi enrollRecognizedFace:", error);
        alert(error.message || "Không thể ghi mẫu khuôn mặt");
    } finally {
        if (enrollFaceButton) {
            enrollFaceButton.textContent = "Ghi góc khuôn mặt";
            enrollFaceButton.disabled = !currentRecognizedDriverId;
        }
    }
}

function drawText(ctx, text, x, y, color = "#00ff88", size = 20) {
    ctx.font = `bold ${size}px Arial`;
    ctx.fillStyle = color;
    ctx.strokeStyle = "rgba(0,0,0,0.85)";
    ctx.lineWidth = 4;
    ctx.strokeText(text, x, y);
    ctx.fillText(text, x, y);
}

function drawPoint(ctx, x, y, color, radius = 2.5) {
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
}

function drawMirroredVideo(ctx, destX, destY, destW, destH) {
    ctx.save();
    ctx.translate(destX + destW, destY);
    ctx.scale(-1, 1);
    ctx.drawImage(videoElement, 0, 0, destW, destH);
    ctx.restore();
}

function drawLocalLikeOriginal(ctx) {
    drawMirroredVideo(ctx, 0, 0, HALF_WIDTH, CANVAS_HEIGHT);

    drawText(ctx, "CAMERA GOC", 20, 35, "#ffff00", 22);
    drawText(ctx, "DRIVER: NOT READY", 20, 70, "#00ff00", 16);
    drawText(ctx, "VEHICLE: --", 20, 100, "#ffff00", 16);
    drawText(ctx, "SHIFT: --", 20, 130, "#00ffff", 16);
}

function drawFaceMeshAI(ctx, ai) {
    const offsetX = HALF_WIDTH;

    drawMirroredVideo(ctx, offsetX, 0, HALF_WIDTH, CANVAS_HEIGHT);

    if (!ai || !Array.isArray(ai.landmarks) || ai.landmarks.length === 0) {
        drawText(ctx, "FACE MESH AI", offsetX + 20, 35, "#00ff00", 22);
        drawText(ctx, "NO FACE DETECTED", offsetX + 20, 80, "#ff3333", 22);
        return;
    }

    for (const lm of ai.landmarks) {
        const x = offsetX + lm.x * HALF_WIDTH;
        const y = lm.y * CANVAS_HEIGHT;
        drawPoint(ctx, x, y, "rgba(0,255,120,0.75)", 1.3);
    }

    if (Array.isArray(ai.left_eye_indexes)) {
        for (const index of ai.left_eye_indexes) {
            const lm = ai.landmarks[index];
            if (lm) drawPoint(ctx, offsetX + lm.x * HALF_WIDTH, lm.y * CANVAS_HEIGHT, "#00ff00", 3.5);
        }
    }

    if (Array.isArray(ai.right_eye_indexes)) {
        for (const index of ai.right_eye_indexes) {
            const lm = ai.landmarks[index];
            if (lm) drawPoint(ctx, offsetX + lm.x * HALF_WIDTH, lm.y * CANVAS_HEIGHT, "#ffff00", 3.5);
        }
    }

    if (Array.isArray(ai.mouth_indexes)) {
        for (const index of ai.mouth_indexes) {
            const lm = ai.landmarks[index];
            if (lm) drawPoint(ctx, offsetX + lm.x * HALF_WIDTH, lm.y * CANVAS_HEIGHT, "#ff00ff", 3.5);
        }
    }

    const eyeColor = ai.eye_status === "EYES CLOSED" ? "#ff3333" : "#00ff00";
    const mouthColor = ai.mouth_status === "MOUTH OPEN" ? "#ff3333" : "#00ff00";
    const headColor = ai.head_status === "HEAD DOWN" ? "#ff3333" : "#00ff00";
    const drowsyColor = ai.drowsy_status !== "NORMAL" ? "#ff3333" : "#00ff00";

    drawText(ctx, "FACE MESH AI", offsetX + 20, 35, "#00ff00", 22);
    drawText(ctx, `EAR: ${ai.ear ?? "--"}`, offsetX + 20, 70, "#ffff00", 18);
    drawText(ctx, `MAR: ${ai.mar ?? "--"}`, offsetX + 20, 100, "#ff66ff", 18);
    drawText(ctx, `STATUS: ${ai.eye_status || "--"}`, offsetX + 20, 130, eyeColor, 18);
    drawText(ctx, `MOUTH: ${ai.mouth_status || "--"}`, offsetX + 20, 160, mouthColor, 18);
    drawText(ctx, `HEAD: ${ai.head_status || "--"}`, offsetX + 20, 190, headColor, 18);
    drawText(ctx, `DROWSY: ${ai.drowsy_status || "--"}`, offsetX + 20, 220, drowsyColor, 18);
}

function drawPreviewLoop() {
    if (!webcamStream || !videoElement.videoWidth || !cameraImg) return;

    previewCanvas.width = CANVAS_WIDTH;
    previewCanvas.height = CANVAS_HEIGHT;

    previewCtx.clearRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);

    drawLocalLikeOriginal(previewCtx);
    drawFaceMeshAI(previewCtx, latestAI);

    cameraImg.src = previewCanvas.toDataURL("image/jpeg", 0.78);

    previewAnimationId = requestAnimationFrame(drawPreviewLoop);
}

async function analyzeCurrentFrame() {
    if (!webcamStream || !videoElement.videoWidth) return;

    analyzeCanvas.width = 320;
    analyzeCanvas.height = 240;

    analyzeCtx.save();
    analyzeCtx.scale(-1, 1);
    analyzeCtx.drawImage(videoElement, -320, 0, 320, 240);
    analyzeCtx.restore();

    const imageBase64 = analyzeCanvas.toDataURL("image/jpeg", 0.65);

    try {
        const response = await fetch(`${BACKEND_URL}/api/analyze_frame`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                image: imageBase64
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.message || "Không phân tích được frame");
        }

        latestAI = data.ai;
        updateCameraPanel(data.ai, data.recognition);
    } catch (error) {
        console.error("Lỗi analyzeCurrentFrame:", error);
    }
}


async function startCamera() {
    try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            alert("Trình duyệt không hỗ trợ camera.");
            return;
        }

        webcamStream = await navigator.mediaDevices.getUserMedia({
            video: {
                width: { ideal: 640 },
                height: { ideal: 480 },
                facingMode: "user"
            },
            audio: false
        });

        videoElement.srcObject = webcamStream;
        await videoElement.play();

        latestAI = null;
        aiLogEntries = [];
        renderAILog();

        if (previewAnimationId) {
            cancelAnimationFrame(previewAnimationId);
        }

        drawPreviewLoop();

        if (analyzeTimer) {
            clearInterval(analyzeTimer);
        }

        analyzeTimer = setInterval(analyzeCurrentFrame, 700);

        alert("Đã bật camera trình duyệt");
    } catch (error) {
        console.error("Lỗi startCamera:", error);
        alert("Không thể mở camera. Hãy cấp quyền camera cho website.");
    }
}

function stopCamera() {
    if (analyzeTimer) {
        clearInterval(analyzeTimer);
        analyzeTimer = null;
    }

    if (previewAnimationId) {
        cancelAnimationFrame(previewAnimationId);
        previewAnimationId = null;
    }

    if (webcamStream) {
        webcamStream.getTracks().forEach(track => track.stop());
        webcamStream = null;
    }

    latestAI = null;

    if (cameraImg) {
        cameraImg.src = "";
    }

    aiLogEntries = [];
    renderAILog();

    alert("Đã dừng camera");
}

function captureImage() {
    if (!cameraImg || !cameraImg.src) {
        alert("Chưa có hình ảnh để chụp");
        return;
    }

    const link = document.createElement("a");
    link.href = cameraImg.src;
    link.download = `driverguard_capture_${Date.now()}.jpg`;
    link.click();
}

document.addEventListener("DOMContentLoaded", () => {
    renderAILog();
});