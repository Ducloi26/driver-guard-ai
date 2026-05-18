from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/register")
def register():
    return render_template("register.html")

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

@app.route("/drivers")
def drivers():
    return render_template("drivers.html")

@app.route("/vehicles")
def vehicles():
    return render_template("vehicles.html")

@app.route("/shifts")
def shifts():
    return render_template("shifts.html")

@app.route("/camera")
def camera():
    return render_template("camera.html")

@app.route("/alerts")
def alerts():
    return render_template("alerts.html")

@app.route("/stats")
def stats():
    return render_template("stats.html")

@app.route("/settings")
def settings():
    return render_template("settings.html")

@app.route("/profile")
def profile():
    return render_template("profile.html")


@app.route("/add-driver")
def add_driver():
    return render_template("add_driver.html")

if __name__ == "__main__":
    app.run(debug=True)