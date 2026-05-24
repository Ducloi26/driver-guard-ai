const cameraImg = document.querySelector(".camera-stream");

let cameraStatusTimer = null;

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
    element.textContent = text;
    element.className = `badge ${className}`;
}

function updateCameraPanel(data) {
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

    if (data.status === "RECOGNIZED") {
        driverName.textContent = data.driver_name;
        driverAvatar.textContent = getInitials(data.driver_name);
        driverVerify.textContent = `Đã xác thực khuôn mặt - độ chính xác ${data.confidence}%`;
        vehiclePlate.textContent = textOrDash(data.vehicle_plate);
        shiftInfo.textContent = `${textOrDash(data.shift_name)} | ${textOrDash(data.shift_time)}`;
        driverPhone.textContent = textOrDash(data.phone);
        setBadge(recognitionBadge, "Đã xác thực", "badge-success");

        driverChip.textContent = `Tài xế: ${data.driver_name}`;
        confidenceChip.textContent = `Độ khớp: ${data.confidence}%`;
        vehicleChip.textContent = `Xe: ${textOrDash(data.vehicle_plate)}`;
        statusChip.textContent = "Trạng thái: Đã nhận diện";
        statusChip.classList.remove("danger");
        return;
    }

    if (data.status === "UNKNOWN_DRIVER") {
        driverName.textContent = "Không xác định";
        driverAvatar.textContent = "??";
        driverVerify.textContent = `Không khớp dữ liệu tài xế - độ gần nhất ${data.confidence}%`;
        vehiclePlate.textContent = "--";
        shiftInfo.textContent = "--";
        driverPhone.textContent = "--";
        setBadge(recognitionBadge, "Không xác định", "badge-danger");

        driverChip.textContent = "Tài xế: Không xác định";
        confidenceChip.textContent = `Độ khớp: ${data.confidence}%`;
        vehicleChip.textContent = "Xe: --";
        statusChip.textContent = "Trạng thái: Chưa khớp dữ liệu";
        statusChip.classList.add("danger");
        return;
    }

    driverName.textContent = "Đang chờ nhận diện";
    driverAvatar.textContent = "--";
    driverVerify.textContent = "Camera chưa xác thực tài xế";
    vehiclePlate.textContent = "--";
    shiftInfo.textContent = "--";
    driverPhone.textContent = "--";
    setBadge(recognitionBadge, "Đang chờ", "badge-warning");

    driverChip.textContent = "Tài xế: Đang chờ";
    confidenceChip.textContent = "Độ khớp: --";
    vehicleChip.textContent = "Xe: --";
    statusChip.textContent = "Trạng thái: Đang phân tích";
    statusChip.classList.remove("danger");
}

function refreshCameraStatus() {
    fetch("/camera_status")
        .then(response => response.json())
        .then(updateCameraPanel)
        .catch(error => {
            console.error("Lỗi refreshCameraStatus:", error);
        });
}

function startStatusPolling() {
    refreshCameraStatus();

    if (cameraStatusTimer) {
        clearInterval(cameraStatusTimer);
    }

    cameraStatusTimer = setInterval(refreshCameraStatus, 1000);
}

function stopStatusPolling() {
    if (cameraStatusTimer) {
        clearInterval(cameraStatusTimer);
        cameraStatusTimer = null;
    }
}

function startCamera() {
    fetch("/start_camera", {
        method: "POST"
    })
    .then(response => response.json())
    .then(data => {
        cameraImg.src = "/video_feed?t=" + new Date().getTime();
        startStatusPolling();
        alert(`Đã bắt đầu camera. Đã tải ${data.known_faces || 0} khuôn mặt đăng ký.`);
    })
    .catch(error => {
        console.error("Lỗi startCamera:", error);
        alert("Không thể bắt đầu camera");
    });
}

function stopCamera() {
    fetch("/stop_camera", {
        method: "POST"
    })
    .then(response => response.json())
    .then(data => {
        cameraImg.src = "";
        stopStatusPolling();
        refreshCameraStatus();
        alert("Đã dừng camera");
    })
    .catch(error => {
        console.error("Lỗi stopCamera:", error);
        alert("Không thể dừng camera");
    });
}

function captureImage() {
    fetch("/capture_image", {
        method: "POST"
    })
    .then(response => response.json())
    .then(data => {
        alert(data.message);
    })
    .catch(error => {
        console.error("Lỗi captureImage:", error);
        alert("Không thể chụp ảnh minh chứng");
    });
}
