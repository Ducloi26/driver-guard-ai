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
    if (strong) {
        strong.textContent = mapped.text;
    }

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

function updateCameraPanel(ai) {
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

    if (driverName) driverName.textContent = "Camera trình duyệt";
    if (driverAvatar) driverAvatar.textContent = "AI";
    if (driverVerify) driverVerify.textContent = "Đang phân tích webcam từ trình duyệt";
    if (vehiclePlate) vehiclePlate.textContent = "--";
    if (shiftInfo) shiftInfo.textContent = "--";
    if (driverPhone) driverPhone.textContent = "--";

    setBadge(recognitionBadge, "AI realtime", "badge-success");

    if (driverChip) driverChip.textContent = "Tài xế: Đang phân tích";
    if (confidenceChip) {
        confidenceChip.textContent = `EAR: ${ai.ear ?? "--"} | MAR: ${ai.mar ?? "--"}`;
    }
    if (vehicleChip) vehicleChip.textContent = "Xe: --";

    if (statusChip) {
        statusChip.textContent = `Trạng thái: ${ai.drowsy_status || "NORMAL"}`;
        statusChip.classList.toggle("danger", ai.drowsy_status && ai.drowsy_status !== "NORMAL");
    }
}

function drawPoint(ctx, x, y, color, radius = 2.5) {
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
}

function drawText(ctx, text, x, y, color = "#00ff88", size = 20) {
    ctx.font = `bold ${size}px Arial`;
    ctx.fillStyle = color;
    ctx.strokeStyle = "rgba(0, 0, 0, 0.8)";
    ctx.lineWidth = 4;
    ctx.strokeText(text, x, y);
    ctx.fillText(text, x, y);
}

function drawLandmarks(ctx, ai, width, height) {
    if (!ai || !Array.isArray(ai.landmarks) || ai.landmarks.length === 0) {
        drawText(ctx, "NO FACE DETECTED", 20, 80, "#ff3b30", 22);
        return;
    }

    for (const lm of ai.landmarks) {
        const x = lm.x * width;
        const y = lm.y * height;
        drawPoint(ctx, x, y, "rgba(0, 255, 120, 0.75)", 1.4);
    }

    if (Array.isArray(ai.left_eye_indexes)) {
        for (const index of ai.left_eye_indexes) {
            const lm = ai.landmarks[index];
            if (lm) drawPoint(ctx, lm.x * width, lm.y * height, "#00ff00", 3.5);
        }
    }

    if (Array.isArray(ai.right_eye_indexes)) {
        for (const index of ai.right_eye_indexes) {
            const lm = ai.landmarks[index];
            if (lm) drawPoint(ctx, lm.x * width, lm.y * height, "#ffff00", 3.5);
        }
    }

    if (Array.isArray(ai.mouth_indexes)) {
        for (const index of ai.mouth_indexes) {
            const lm = ai.landmarks[index];
            if (lm) drawPoint(ctx, lm.x * width, lm.y * height, "#ff00ff", 3.5);
        }
    }

    drawText(ctx, "FACE MESH AI", 20, 35, "#00ff88", 22);
    drawText(ctx, `EAR: ${ai.ear ?? "--"}`, 20, 70, "#ffff00", 18);
    drawText(ctx, `MAR: ${ai.mar ?? "--"}`, 20, 100, "#ff66ff", 18);
    drawText(ctx, `EYE: ${ai.eye_status || "--"}`, 20, 130, ai.eye_status === "EYES CLOSED" ? "#ff3b30" : "#00ff88", 18);
    drawText(ctx, `MOUTH: ${ai.mouth_status || "--"}`, 20, 160, ai.mouth_status === "MOUTH OPEN" ? "#ffcc00" : "#00ff88", 18);
    drawText(ctx, `HEAD: ${ai.head_status || "--"}`, 20, 190, ai.head_status === "HEAD DOWN" ? "#ff3b30" : "#00ff88", 18);
    drawText(ctx, `DROWSY: ${ai.drowsy_status || "--"}`, 20, 220, ai.drowsy_status !== "NORMAL" ? "#ff3b30" : "#00ff88", 18);
}

function drawPreviewLoop() {
    if (!webcamStream || !videoElement.videoWidth || !cameraImg) return;

    const width = videoElement.videoWidth;
    const height = videoElement.videoHeight;

    previewCanvas.width = width;
    previewCanvas.height = height;

    previewCtx.save();
    previewCtx.scale(-1, 1);
    previewCtx.drawImage(videoElement, -width, 0, width, height);
    previewCtx.restore();

    drawLandmarks(previewCtx, latestAI, width, height);

    cameraImg.src = previewCanvas.toDataURL("image/jpeg", 0.75);

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
        updateCameraPanel(data.ai);
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