const API = "http://127.0.0.1:8000";

// Calls the API and returns the parsed JSON body.
// For error responses it throws an Error carrying the server's
// {"detail": "..."} message so the caller can show it to the user.
async function api(path, options = {}) {
    let res;
    try {
        res = await fetch(`${API}${path}`, options);
    } catch (err) {
        throw new Error("Cannot reach the server. Is the backend running?");
    }

    let data = await res.json().catch(() => ({}));

    if (!res.ok) {
        throw new Error(data.detail || `Request failed (${res.status})`);
    }
    return data;
}

function showError(err) {
    showMsg(err.message, true);
}

async function register() {
    let student = document.getElementById("studentSelect").value;
    let course = document.getElementById("courseSelect").value;

    let data = await api("/register", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            student_id: parseInt(student),
            course_id: parseInt(course),
            semester_id: 1
        })
    }).catch(showError);

    if (data) showMsg(data.message);

    loadRegistrations();
    loadWaitlist();
}

// LOAD REGISTRATIONS
async function loadRegistrations() {
    let data = await api("/registrations").catch(showError);
    if (!data) return;

    let list = document.getElementById("list");
    list.innerHTML = "";

    data.forEach(r => {
        let li = document.createElement("li");
        li.innerText = `👤 ${r.student_name} → 📘 ${r.course_name}`;
        list.appendChild(li);
    });
}

// LOAD WAITLIST
async function loadWaitlist() {
    let data = await api("/waitlist").catch(showError);
    if (!data) return;

    let list = document.getElementById("waitlist");
    list.innerHTML = "";

    data.forEach(w => {
        let li = document.createElement("li");
        li.innerText = `⏳ ${w.student_name} → ${w.course_name} (Pos: ${w.position})`;
        list.appendChild(li);
    });
}

async function dropCourse() {
    let student = document.getElementById("dropStudent").value;
let course = document.getElementById("dropCourse").value;

    let data = await api("/drop", {
        method: "DELETE",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            student_id: parseInt(student),
            course_id: parseInt(course),
            semester_id: 1
        })
    }).catch(showError);

    if (data) showMsg(data.message);

    loadRegistrations();
    loadWaitlist();
}

function showMsg(text, isError = false) {
    let msg = document.getElementById("msg");
    msg.innerText = text;
    msg.classList.toggle("error", isError);
}

async function loadCourses() {
    let data = await api("/courses").catch(showError);
    if (!data) return;

    let list = document.getElementById("courses");
    list.innerHTML = "";

    data.forEach(c => {
        let li = document.createElement("li");
        li.innerText = `📘 ${c.course_name} | Capacity: ${c.capacity}`;
        list.appendChild(li);
    });
}

async function addStudent() {
    let name = document.getElementById("name").value;
    let email = document.getElementById("email").value;

    let formData = new FormData();
    formData.append("name", name);
    formData.append("email", email);

    let data = await api("/add-student", {
        method: "POST",
        body: formData
    }).catch(showError);

    if (data) showMsg(data.message);

    loadStudents();
}
async function loadStudents() {
    let data = await api("/students").catch(showError);
    if (!data) return;

    console.log("STUDENTS:", data); // 👈 IMPORTANT

    let select = document.getElementById("studentSelect");
    select.innerHTML = "";

    data.forEach(s => {
        let opt = document.createElement("option");
        opt.value = s.student_id;
        opt.text = s.student_name;
        select.appendChild(opt);
    });
    document.getElementById("dropStudent").innerHTML =
    document.getElementById("studentSelect").innerHTML;
}
async function loadCoursesDropdown() {
    let data = await api("/courses").catch(showError);
    if (!data) return;

    let select = document.getElementById("courseSelect");
    select.innerHTML = "";

    data.forEach(c => {
        let opt = document.createElement("option");
        opt.value = c.course_id;
        opt.text = c.course_name;
        select.appendChild(opt);
    });
    document.getElementById("dropCourse").innerHTML =
    document.getElementById("courseSelect").innerHTML;
}

window.onload = () => {
    loadStudents();
    loadCoursesDropdown();
    loadRegistrations();
    loadWaitlist();
};
