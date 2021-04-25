from logging import debug
from flask import Flask, render_template, request
import sys

import dymoprint

app = Flask(__name__)

@app.route('/')
def landing_page():
    return render_template('index.html')

@app.route('/print')
def input_page():
    # for now hardcode max 3 lines because more is super small
    line1 = request.args.get('lineOne')
    line2 = request.args.get('lineTwo')
    line3 = request.args.get('lineThree')

    if line1 != None:
        if len(line1.strip()) == 0:
            return render_template('index.html', error="Label has to contain text on first line")
        else:
            emulated_args = [line1]

        if line2 != None and len(line2.strip()) > 0:
            emulated_args.append(line2)

        if line3 != None and len(line3.strip()) > 0:
            emulated_args.append(line3)

        args = dymoprint.parse_args(emulated_args)
        try:
            dymoprint.main(args)
            return render_template('index.html', success="Printed label")
        except dymoprint.DymoPrintException as e:
            # Exceptions already caught by dymoprint
            return render_template('index.html', error=e.message)
        except Exception:    
            # All other generic errors that might happen
            if not args.pdb:
                raise
            import traceback
            import pdb
            type, value, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
    else:
        return render_template('index.html', error="You have to print something")

if __name__ == '__main__':
    app.run('0.0.0.0', debug=True)