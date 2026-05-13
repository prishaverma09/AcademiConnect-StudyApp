from app import app, db
from models import User, Course, Skill, LibraryQuestion, FileResource
from datetime import datetime

with app.app_context():
    # Create a test mentor
    if not User.query.filter_by(email="mentor@vit.edu").first():
        mentor = User(
            name="Alex Smith",
            email="mentor@vit.edu",
            college="VIT Bhopal University",
            year="Fourth Year",
            study_vibe="Quiet Library",
            mentor_status=True,
            trust_score=4.9,
            is_verified=True
        )
        db.session.add(mentor)
        db.session.flush()
        
        # Add skills
        s1 = Skill(name="Python", user_id=mentor.id)
        s2 = Skill(name="Data Structures", user_id=mentor.id)
        db.session.add_all([s1, s2])

    # Create a test course
    if not Course.query.filter_by(code="CS101").first():
        course = Course(code="CS101", name="Introduction to Computer Science")
        db.session.add(course)

    # Create a test file
    if not FileResource.query.filter_by(filename="Python_Basics.pdf").first():
        # We need a user to 'upload' it
        user = User.query.first()
        if user:
            file = FileResource(
                filename="Python_Basics.pdf",
                file_path="uploads/Python_Basics.pdf",
                course_code="CS101",
                uploaded_by=user.id
            )
            db.session.add(file)

    db.session.commit()
    print("Database seeded successfully!")
