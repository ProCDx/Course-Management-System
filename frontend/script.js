const API = "http://127.0.0.1:8000";

async function register() {
    let student = document.getElementById("studentSelect").value;
    let course = document.getElementById("courseSelect").value;

    let res = await fetch(`${API}/register`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            student_id: parseInt(student),
            course_id: parseInt(course),
            semester_id: 1
        })
    });

    let data = await res.json();
    showMsg(data.message);

    loadRegistrations();
    loadWaitlist();
}

// LOAD REGISTRATIONS
async function loadRegistrations() {
    let res = await fetch(`${API}/registrations`);
    let data = await res.json();

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
    let res = await fetch(`${API}/waitlist`);
    let data = await res.json();

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

    let res = await fetch(`${API}/drop`, {
        method: "DELETE",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            student_id: parseInt(student),
            course_id: parseInt(course),
            semester_id: 1
        })
    });

    let data = await res.json();
    showMsg(data.message);

    loadRegistrations();
    loadWaitlist();
}

function showMsg(text) {
    document.getElementById("msg").innerText = text;
}

async function loadCourses() {
    let res = await fetch(`${API}/courses`);
    let data = await res.json();

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

    let res = await fetch(`${API}/add-student`, {
        method: "POST",
        body: formData
    });

    let data = await res.json();
    showMsg(data.message);

    loadStudents();
}
async function loadStudents() {
    let res = await fetch(`${API}/students`);
    let data = await res.json();

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
    let res = await fetch(`${API}/courses`);
    let data = await res.json();

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
//DEBUG
loadStudents();
loadCoursesDropdown();
async function loadStudents() {
    let res = await fetch(`${API}/students`);
    let data = await res.json();

    console.log("STUDENTS:", data);  // 👈 ADD THIS

    let select = document.getElementById("studentSelect");
    select.innerHTML = "";

    data.forEach(s => {
        let opt = document.createElement("option");
        opt.value = s.student_id;
        opt.text = s.student_name;
        select.appendChild(opt);
    });
}

window.location.href = "dashboard.html";

localStorage.setItem("student_id", selectedId);

let student = localStorage.getItem("student_id");

window.onload = () => {
    loadStudents();
    loadCoursesDropdown();
};