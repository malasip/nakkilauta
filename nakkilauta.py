from datetime import datetime
from functools import wraps
from flask import Flask, render_template, redirect, request, flash, url_for, abort
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from secrets import token_bytes, token_urlsafe
from werkzeug.security import generate_password_hash, check_password_hash
from wtforms import StringField, PasswordField, TextAreaField, SelectMultipleField, validators
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from urllib.parse import urlparse, urljoin
from sqlalchemy import exc
from flask_wtf.csrf import CSRFProtect
from wtforms.ext.sqlalchemy.fields import QuerySelectMultipleField


app = Flask(__name__)
app.secret_key = token_bytes(128)
register_token = token_urlsafe(20)
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.init_app(app)

db = SQLAlchemy(app)

# User model and functions
class User(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    username = db.Column(db.String, nullable = False, unique = True)
    display_name = db.Column(db.String, nullable = False, unique = True)
    pwhash = db.Column(db.String, nullable = False)
    active = db.Column(db.Boolean, default = False)
    superuser = db.Column(db.Boolean, default = False)
    threads = db.relationship('Thread', backref = db.backref('user', remote_side = [id]))
    replies = db.relationship('Reply', backref = db.backref('user', remote_side = [id]))

    @property
    def is_active(self):
        return self.active

    @property
    def is_authenticated(self):
        return True
    @property
    def is_anonymous(self):
        return False

    @property
    def is_superuser(self):
        return self.superuser

    def get_id(self):
        return self.id

    def setPassword(self, password):
        self.pwhash = generate_password_hash(password)

    def checkPassword(self, password):
        return check_password_hash(self.pwhash, password)

# User creation/ edit forms
class UserForm(FlaskForm):
    username = StringField('Username', validators = [validators.InputRequired()])
    password = PasswordField('Password', validators = [validators.InputRequired()])
    display_name = StringField('Display name', validators = [validators.InputRequired()])
    token = StringField('Register token', validators = [validators.InputRequired()])

# User login form
class LoginForm(FlaskForm):
    username = StringField('Username', validators = [validators.InputRequired()])
    password = PasswordField('Password', validators = [validators.InputRequired()])

# User login manager
@login_manager.user_loader
def loadUser(id):
    return User.query.get(id)
    #return db.session.query(User).filter(User.id == id).one_or_none()

@login_manager.unauthorized_handler
def unauthorized(content = None):
    title = 'Unauthorized'
    if not content:
        content = 'You need to be logged in to access this page'
    return render_template('40x.html', title = title, content = content)

moderators = db.Table('moderators', db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('board_id', db.Integer, db.ForeignKey('board.id'))
)

# User helper functions
def superuser_required(func):
    @wraps(func)
    def verify(*args, **kwargs):
        if not current_user.is_superuser:
            return unauthorized('You need to be a superuser to access this page')
        return func(*args, **kwargs)
    return verify

class Board(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    display_name = db.Column(db.String, nullable = False)
    name = db.Column(db.String, nullable = False, unique = True)
    modified = db.Column(db.DateTime)
    deleted = db.Column(db.DateTime)
    threads = db.relationship('Thread', backref = db.backref('board', remote_side = [id]))
    moderators = db.relationship('User', secondary = moderators, backref = 'moderated_boards')

class Thread(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    title = db.Column(db.String, nullable = False)
    message = db.Column(db.String, nullable = False)
    timestamp = db.Column(db.DateTime, nullable = False, default = datetime.utcnow)
    modified = db.Column(db.DateTime)
    deleted = db.Column(db.DateTime)
    locked = db.Column(db.Boolean, default = False)
    board_id = db.Column(db.Integer, db.ForeignKey('board.id'))
    replies = db.relationship('Reply', backref = db.backref('thread', remote_side = [id]))

class Reply(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    message = db.Column(db.String, nullable = False)
    timestamp = db.Column(db.DateTime, nullable = False, default = datetime.utcnow)
    modified = db.Column(db.DateTime)
    deleted = db.Column(db.DateTime)
    thread_id = db.Column(db.Integer, db.ForeignKey('thread.id'))
    parent_id = db.Column(db.Integer, db.ForeignKey('reply.id'))
    replies = db.relationship('Reply')


# Thread forms
class ThreadForm(FlaskForm):
    title = StringField('Title', validators = [validators.InputRequired()])
    message = TextAreaField('Message', validators = [validators.InputRequired()])

class ReplyForm(FlaskForm):
    message = TextAreaField('Message', validators = [validators.InputRequired()])

# Initialize database
@app.before_first_request
class initDB():
    db.create_all()
    user = User(username = 'superuser', display_name = 'Admin', active = True, superuser = True)
    user.setPassword('superuser')
    db.session.add(user)
    board = Board(name = 'random', display_name = 'Random')
    board.moderators.append(user)
    db.session.add(board)
    db.session.add(Board(name = 'aihevapaa', display_name = 'Aihe vapaa'))
    db.session.commit()

# Adminstrative forms
class BoardForm(FlaskForm):
    display_name = StringField('Name', validators = [validators.InputRequired()])
    moderators = SelectMultipleField('Moderators', coerce=int)
    #moderators = QuerySelectMultipleField('Moderators', query_factory=User.query.filter(User.active == True).all, get_label=lambda u: u.username)
    #moderators = QuerySelectMultipleField('Moderators', query_factory=db.session.query(User).filter_by(active = True).all, get_label=lambda u: u.username)

# Url helper
def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

# Error page handlers
@app.errorhandler(400)
def error_page(error):
    print(error)
    boards = Board.query.filter(Board.deleted == None).order_by(Board.name.asc()).all()
    #boards = db.session.query(Board).filter(Board.deleted).order_by(Board.name.asc()).all()
    title = 'Error loading page'
    content = 'There was an error accessing page. Team of monkeys have been dispatched to reseolve the issue.'
    return render_template('40x.html', boards = boards, title = title, content = content)

# Error page handlers
@app.errorhandler(403)
def error_page(error):
    print(error)
    boards = Board.query.filter(Board.deleted == None).order_by(Board.name.asc()).all()
    #boards = db.session.query(Board).filter(Board.deleted).order_by(Board.name.asc()).all()
    title = 'Unauthorized'
    content = 'You are not authorized to perform this action.'
    return render_template('40x.html', boards = boards, title = title, content = content)

@app.errorhandler(404)
def page_not_found(error):
    boards = Board.query.filter(Board.deleted == None).order_by(Board.name.asc()).all()
    #boards = db.session.query(Board).filter(Board.deleted).order_by(Board.name.asc()).all()
    title = 'Page not found'
    return render_template('40x.html', boards = boards, title = title, content = error)

# Application routes

# User endpoints
@app.route('/register', methods = ['GET', 'POST'])
def register():
    form = UserForm()
    if form.validate_on_submit():
        if(form.token.data != register_token):
            flash('Invalid token')
            return redirect(url_for('register'))
        user = User(username = form.username.data, display_name = form.display_name.data)
        user.setPassword(form.password.data)
        try:
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash('User created successfully.')
        except exc.IntegrityError:
            db.session.rollback()
            flash('Username not avalable')
            return redirect(url_for('register'))
        return redirect(url_for('index'))
    return render_template('user_form.html', form = form)

@app.route('/login', methods = ['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        user = User.query.filter(User.username == username).first()
        #user = db.session.query(User).filter(User.username == username).one_or_none()
        if not user:
            flash('Login failed, bad username or password')
            return redirect(url_for('login'))
        if not user.checkPassword(password):
            flash('Login failed, bad username or password')
            return redirect(url_for('login'))
        login_user(user)
        flash(f'Logged in as {user.display_name}')
        next = request.args.get('next')
        if not is_safe_url(next):
            return abort(400)
        return redirect(next or url_for('index'))
    return render_template('user_form.html', form = form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully')
    return redirect(url_for('index'))

### ADMINISTRATIVE ENDPOINTS ###

# Admin panel
@app.route('/admin')
@login_required
@superuser_required
def admin():
    boards = Board.query.order_by(Board.name.asc()).all()
    #boards = db.session.query(Board).order_by(Board.name.asc()).all()
    users = User.query.all()
    #users = db.session.query(User).all()
    return render_template('admin.html', boards = boards, users = users, register_token = register_token)

### USER ENDPOINTS ###

# User activate
@app.route('/admin/user/<int:id>/activate')
@login_required
@superuser_required
def activate_user(id):
    user = User.query.get_or_404(id)
    #user = db.session.query(User).filter(User.id == id).one_or_none()
    if not user:
        abort(404)
    if user.active:
        user.active = False
    else:
        user.active = True
    try:
        db.session.commit()
        flash('User activated activation status changed succesfully')
        next = request.args.get('next')
        if not is_safe_url(next):
            return abort(400)
        return redirect(next or url_for('index'))
    except:
        db.session.rollback()
        flash('There was an error activating user, check server logs for more information')
        return abort(400)

# User set as superuser
@app.route('/admin/user/<int:id>/superuser')
@login_required
@superuser_required
def set_superuser(id):
    user = User.query.get_or_404(id)
    #user = db.session.query(User).filter(User.id == id).one_or_none()
    if not user:
        abort(404)
    if user.superuser and user.name != 'superuser':
        user.superuser = False
    else:
        user.superuser = True
    try:
        db.session.commit()
        flash('Superuser status changed succesfully')
        next = request.args.get('next')
        if not is_safe_url(next):
            return abort(400)
        return redirect(next or url_for('index'))
    except:
        db.session.rollback()
        flash('There was an error setting user as superuser, check server logs for more information')
        return abort(400)

# User delete
@app.route('/admin/user/<int:id>/delete')
@login_required
@superuser_required
def delete_user(id):
    user = User.query.get_or_404(id)
    #user = db.session.query(User).filter(User.id == id).one_or_none()
    if not user:
        abort(404)
    db.session.delete(user)
    try:
        db.session.commit()
        flash('User deleted succesfully')
        next = request.args.get('next')
        if not is_safe_url(next):
            return abort(400)
        return redirect(next or url_for('index'))
    except:
        db.session.rollback()
        flash('There was an error deleting user, check server logs for more information')
        return abort(400)

### BOARD ENDPOINTS ###

# Board create and edit
@app.route('/create', methods = ['GET', 'POST'])
@app.route('/<string:board_name>/edit', methods = ['GET', 'POST'])
@login_required
@superuser_required
def create_board(board_name = None):
    board = Board()
    for user in User.query.filter(User.active).all():
         users = [(user.id, user.username)]
    if board_name:
        board = Board.query.filter(Board.name == board_name).first()
        #board = db.session.query(Board).filter(Board.name == board_name).one_or_none()
        if board == None:
            abort(404)
        form = BoardForm(obj = board)
        form.moderators.choices = users
    else:
        form = BoardForm()
        form.moderators.choices = users
    if form.validate_on_submit():
        board.display_name = form.display_name.data
        board.name = ''.join(form.display_name.data.split()).lower()
        if board_name:
            board.modified = datetime.utcnow()
        else:
            db.session.add(board)
        for id in form.moderators.data:
            board.moderators.append(User.query.get(id))
        try:
            db.session.commit()
            flash('Board saved succesfully')
            next = request.args.get('next')
            if not is_safe_url(next):
                return abort(400)
            return redirect(next or url_for('index'))
        except:
            db.session.rollback()
            flash('Something went wrong, maybe duplicate name?')
            return abort(400)
    return render_template('default_form.html', form = form)

# Board delete
@app.route('/<string:board_name>/delete')
@login_required
@superuser_required
def delete_board(board_name = None):
    board = Board.query.filter(Board.name == board_name).first()
    #board = db.session.query(Board).filter(Board.name == board_name).one_or_none()
    if not board:
        abort(404)
    board.deleted = datetime.utcnow()
    for thread in board.threads:
        for reply in thread.replies:
            reply.deleted = datetime.utcnow()
        thread.deleted = datetime.utcnow()
    db.session.commit()
    flash('Board deleted succesfully')
    next = request.args.get('next')
    if not is_safe_url(next):
        return abort(400)
    return redirect(next or url_for('index'))



### PUBLIC ENDPOINTS ###

# Main site
@app.route('/')
def index():
    if current_user.is_anonymous == True:
        boards = Board.query.filter(Board.deleted == None).order_by(Board.name.asc()).all()
        #boards = db.session.query(Board).filter(Board.deleted == None).order_by(Board.name.asc()).all()
    elif current_user.is_superuser:
        boards = Board.query.order_by(Board.name.asc()).all()
        #boards = db.session.query(Board).order_by(Board.name.asc()).all()
    else:
        boards = Board.query.filter(Board.deleted == None).order_by(Board.name.asc()).all()
        #boards = db.session.query(Board).filter(Board.deleted == None).order_by(Board.name.asc()).all()
    threads = Thread.query.filter(Thread.deleted == None).order_by(Thread.id.desc()).limit(10).all()
    #threads = db.session.query(Thread).filter(Thread.deleted == None).order_by(Thread.id.desc()).limit(10).all()
    return render_template('index.html', boards = boards, threads = threads)

# Board and thread get enpoints
@app.route('/<string:board_name>')
@app.route('/<string:board_name>/<int:thread_id>')
def board(board_name, thread_id = None):
    board = Board.query.filter(Board.name == board_name).first()
    #board = db.session.query(Board).filter(Board.name == board_name).one_or_none()
    if not board:
        abort(404)
    if board.deleted:
        abort(404)
    boards = Board.query.filter(Board.deleted == None).order_by(Board.name.asc()).all()
    #boards = db.session.query(Board).filter(Board.deleted == None).order_by(Board.name.asc()).all()
    if thread_id:
        thread = Thread.query.get_or_404(thread_id)
        #thread = db.session.query(Thread).get(thread_id)
        if thread.deleted:
            abort(404)
        return render_template('thread.html', boards = boards, thread = thread)
    threads = Thread.query.filter(Thread.deleted == None).filter(Thread.board_id == board.id).order_by(Thread.id.desc()).all()
    #threads = db.session.query(Thread).filter(Thread.deleted == None).filter(Thread.board_id == board.id).order_by(Thread.id.desc()).all()
    return render_template('board.html', boards = boards, threads = threads)

# Create endpoints
@app.route('/<string:board_name>/create', methods = ['GET', 'POST'])
@app.route('/<string:board_name>/<int:thread_id>/reply', methods = ['GET', 'POST'])
@app.route('/<string:board_name>/<int:thread_id>/<int:reply_id>/reply', methods = ['GET', 'POST'])
@login_required
def create_thread(board_name, thread_id = None, reply_id = None):
    board = Board.query.filter(Board.name == board_name).first()
    #board = db.session.query(Board).filter(Board.name == board_name).one_or_none()
    if not board:
        abort(404)
    if not thread_id:
        form = ThreadForm()
    else:
        form = ReplyForm()

    if form.validate_on_submit():
        if not reply_id:
            if thread_id:
                thread = Thread.query.get_or_404(thread_id)
                #thread = db.session.query(Thread).filter(Thread.id == thread_id).one_or_none()
                if not thread:
                    abort(404)
                reply = Reply()
                form.populate_obj(reply)
                reply.thread_id = thread.id
                reply.user_id = current_user.get_id()
                db.session.add(reply)
            else:
                thread = Thread()
                form.populate_obj(thread)
                thread.board_id = board.id
                thread.user_id = current_user.get_id()
                db.session.add(thread)
        else:
            if not thread_id:
                abort(404)
            thread = Thread.query.get_or_404(thread_id)
            #thread = db.session.query(Thread).filter(Thread.id == thread_id).one_or_none()
            if not thread:
                abort(404)
            parent = Reply.query.get_or_404(reply_id)
            #parent = db.session.query(Reply).filter(Reply.id == reply_id).one_or_none()
            if not thread:
                abort(404)
            reply = Reply()
            form.populate_obj(reply)
            reply.parent_id = parent.id
            reply.thread_id = thread.id
            reply.user_id = current_user.get_id()
            db.session.add(reply)
        try:
            db.session.commit()
            flash('Post successfull')
            next = request.args.get('next')
            if not is_safe_url(next):
                return abort(400)
            return redirect(next or url_for('index'))
        except:
            db.session.rollback()
            flash('Something went wrong')
            return abort(400)
    return render_template('thread_form.html', form = form)

# Edit endpoints
@app.route('/<string:board_name>/<int:thread_id>/edit', methods = ['GET', 'POST'])
@app.route('/<string:board_name>/<int:thread_id>/<int:reply_id>/edit', methods = ['GET', 'POST'])
@login_required
def edit_thread(board_name, thread_id, reply_id = None):
    if not reply_id:
        thread = Thread.query.get_or_404(thread_id)
        if current_user.get_id() != thread.user_id and current_user not in thread.board.moderators and not current_user.is_superuser:
            abort(403)
        form = ThreadForm(obj = thread)
    elif not thread_id:
        abort(404)
    else:
        reply = Reply.query.get_or_404(reply_id)
        if current_user.get_id() != reply.user_id and current_user not in reply.thread.board.moderators and not current_user.is_superuser:
            abort(403)
        form = ReplyForm(obj = reply)
    if form.validate_on_submit():
        if not reply_id:
            if thread_id:
                #thread = Thread.query.get_or_404(thread_id)
                form.populate_obj(thread)
                thread.modified = datetime.utcnow()
        else:
            #reply = Reply.query.get_or_404(reply_id)
            form.populate_obj(reply)
            reply.modified = datetime.utcnow()
        try:
            db.session.commit()
            flash('Post modified succesfully')
            next = request.args.get('next')
            if not is_safe_url(next):
                return abort(400)
            return redirect(next or url_for('index'))
        except:
            db.session.rollback()
            flash('Something went wrong')
            return abort(400)
    return render_template('thread_form.html', form = form)

# Delete endpoints
@app.route('/<string:board_name>/<int:thread_id>/delete', methods = ['GET', 'POST'])
@app.route('/<string:board_name>/<int:thread_id>/<int:reply_id>/delete', methods = ['GET', 'POST'])
@login_required
def delete_thread(board_name, thread_id, reply_id = None):
    if not reply_id:
        thread = Thread.query.get_or_404(thread_id)
        if current_user.get_id() != thread.user_id and current_user not in thread.board.moderators and not current_user.is_superuser:
            abort(403)
        thread.deleted = datetime.utcnow()
    elif not thread_id:
        abort(404)
    else:
        reply = Reply.query.get_or_404(reply_id)
        if current_user.get_id() != reply.user_id and current_user not in reply.thread.board.moderators and not current_user.is_superuser:
            abort(403)
        reply.deleted = datetime.utcnow()
    db.session.commit()
    flash('Message deleted succesfully')
    next = request.args.get('next')
    if not is_safe_url(next):
        return abort(400)
    return redirect(next or url_for('index'))

if __name__ == '__main__':
    app.run(debug = True)