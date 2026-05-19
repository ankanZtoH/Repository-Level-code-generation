import mysql.connector

db = mysql.connector.connect(host='localhost', user='root', password='password', database='educational_erp')

# Admission Portal

@app.route('/admission')
def admission():
    return render_template('admission.html')

# Student Portal

@app.route('/student')
def student():
    return render_template('student.html')

# Employee Portal

@app.route('/employee')
def employee():
    return render_template('employee.html')

# Alumni Portal

@app.route('/alumni')
def alumni():
    return render_template('alumni.html')

if __name__ == '__main__':
    app.run(debug=True)