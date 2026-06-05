const BACKEND_URL = "https://driver-guard-ai-production.up.railway.app";

const cameraImg = document.querySelector(".camera-stream");

let cameraStatusTimer = null;
let webcamStream = null;
let analyzeTimer = null;

const videoElement = document.createElement("video");
videoElement.autoplay = true;
videoElement.playsInline = true;
videoElement.muted = true;

const canvasElement = document.createElement("canvas");
const canvasContext = canvasElement.getContext("2d");

function textOrDash(value) {
    return value || "--";
}

function getInitials(name) {
    if (!name || name === "Không xác định" || name === "Đang chờ nhận diện") {
        return "--";
    }

    return name
        .trim()
        .split(/\s+/)
        .slice(-2)
        .map(part => part[0])
        .join("")
        .toUpperCase();
}

function setBadge(element, text, className) {
    if (!element) return;
    element.textContent = text;
    element.className = `badge ${className}`;
}

const AI_STATUS_MAP = {
    "EYES OPEN": { text: "Mở", css: "status-success" },
    "EYES CLOSED": { text: "Nhắm", css: "status-danger" },
    "NO FACE": { text: "--", css: "" },
    "NORMAL": { text: "Bình thường", css: "status-success" },
    "MOUTH OPEN": { text: "Mở", css: "status-warning" },
    "YAWNING": { text: "Ngáp", css: "status-danger" },
    "HEAD DOWN": { text: "Cúi", css: "status-danger" },
};

const DROWSY_LEVEL_MAP = {
    "NORMAL": { text: "Thấp", css: "status-success" },
    "TIRED": { text: "Trung bình", css: "status-warning" },
    "DROWSY": { text: "Cao", css: "status-danger" },
    "HEAD DOWN ALERT": { text: "Cao", css: "status-danger" },
};

let aiLogEntries = [];

function setStatusBox(id, mapped) {
    const box = document.getElementById(id);
    if (!box) return;

    const strong = box.querySelector("strong");
    if (strong) {
        strong.textContent = mapped.text;
    }

    box.className = "status-box " + mapped.css;
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
        newEntry = { title: "Phát hiện nhắm mắt", detail: `${now} - EAR: ${ai.ear ?? "--"}` };
    } else if (ai.mouth_status === "MOUTH OPEN") {
        newEntry = { title: "Phát hiện mở miệng/ngáp", detail: `${now} - MAR: ${ai.mar ?? "--"}` };
    } else if (ai.head_status === "HEAD DOWN") {
        newEntry = { title: "Phát hiện cúi đầu", detail: `${now} - Đầu cúi xuống` };
    } else if (ai.drowsy_status === "DROWSY" || ai.drowsy_status === "TIRED") {
        newEntry = { title: "Cảnh báo buồn ngủ", detail: `${now} - ${ai.drowsy_status}` };
    }

    if (newEntry) {
        aiLogEntries.unshift(newEntry);
        if (aiLogEntries.length > 10) aiLogEntries.length = 10;
        renderAILog();
    }
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

    for (const e of aiLogEntries) {
        logList.appendChild(createLogItem(e.title, e.detail));
    }
}

function updateCameraPanel(data) {
    const ai = data.ai || data;

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

    if (recognitionBadge) {
        setBadge(recognitionBadge, "AI realtime", "badge-success");
    }

    if (driverChip) driverChip.textContent = "Tài xế: Đang phân tích";
    if (confidenceChip) confidenceChip.textContent = `EAR: ${ai.ear ?? "--"} | MAR: ${ai.mar ?? "--"}`;
    if (vehicleChip) vehicleChip.textContent = "Xe: --";

    if (statusChip) {
        statusChip.textContent = `Trạng thái: ${ai.drowsy_status || "NORMAL"}`;
        if (ai.drowsy_status && ai.drowsy_status !== "NORMAL") {
            statusChip.classList.add("danger");
        } else {
            statusChip.classList.remove("danger");
        }
    }
}

function drawVideoToPreview() {
    if (!cameraImg || !videoElement.videoWidth) return;

    canvasElement.width = videoElement.videoWidth;
    canvasElement.height = videoElement.videoHeight;

    canvasContext.drawImage(videoElement, 0, 0, canvasElement.width, canvasElement.height);

    cameraImg.src = canvasElement.toDataURL("image/jpeg", 0.75);

    if (webcamStream) {
        requestAnimationFrame(drawVideoToPreview);
    }
}

async function analyzeCurrentFrame() {
    if (!webcamStream || !videoElement.videoWidth) return;

    canvasElement.width = 320;
    canvasElement.height = 240;

    canvasContext.drawImage(videoElement, 0, 0, canvasElement.width, canvasElement.height);

    const imageBase64 = canvasElement.toDataURL("image/jpeg", 0.7);

    try {
        const response = await fetch(`${BACKEND_URL}/api/analyze_frame`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                image: imageBase64,
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.message || "Không phân tích được frame");
        }

        updateCameraPanel(data);
    } catch (error) {
        console.error("Lỗi analyzeCurrentFrame:", error);
    }
}

async function startCamera() {
    try {
        webcamStream = await navigator.mediaDevices.getUserMedia({
            video: {
                width: { ideal: 640 },
                height: { ideal: 480 },
                facingMode: "user",
            },
            audio: false,
        });

        videoElement.srcObject = webcamStream;

        await videoElement.play();

        drawVideoToPreview();

        if (analyzeTimer) {
            clearInterval(analyzeTimer);
        }

        analyzeTimer = setInterval(analyzeCurrentFrame, 700);

        aiLogEntries = [];
        renderAILog();

        alert("Đã bật camera trình duyệt");
    } catch (error) {
        console.error("Lỗi startCamera:", error);
        alert("Không thể mở camera trình duyệt. Hãy cấp quyền camera cho website.");
    }
}

function stopCamera() {
    if (analyzeTimer) {
        clearInterval(analyzeTimer);
        analyzeTimer = null;
    }

    if (webcamStream) {
        webcamStream.getTracks().forEach(track => track.stop());
        webcamStream = null;
    }

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