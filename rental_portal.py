
# ==========================================
# COMPANY LOGIN — WE-SELL BUSINESS PORTAL
# ==========================================

@rental_portal.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        with db() as conn:
            company = conn.execute(
                """
                SELECT *
                FROM rental_companies
                WHERE email=?
                """,
                (email,)
            ).fetchone()

        if (
            company
            and check_password_hash(
                company["password_hash"],
                password
            )
        ):
            session.clear()
            session["rental_company_id"] = company["id"]

            return redirect(
                url_for("rental_portal.dashboard")
            )

        flash("Incorrect email or password.")

    return page(
        "Rental Company Login",
        """
        <style>
        .rental-login-layout {
            display: grid;
            grid-template-columns: 1fr 1fr;
            background: #ffffff;
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 15px 45px rgba(4,27,52,.12);
            min-height: 580px;
        }

        .rental-login-left {
            background: linear-gradient(
                145deg, #041b34, #0a355b
            );
            color: white;
            padding: 48px 36px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }

        .rental-brand {
            font-size: 30px;
            font-weight: 900;
            color: #ffc400;
            letter-spacing: -1px;
        }

        .rental-brand-sub {
            color: #bad1e5;
            font-size: 12px;
            margin-top: 4px;
        }

        .rental-login-left h1 {
            font-size: 36px;
            line-height: 1.2;
            color: white;
            margin: 32px 0 18px;
        }

        .rental-login-left p {
            color: #d5e3f0;
            font-size: 15px;
            line-height: 1.8;
        }

        .rental-feature {
            display: flex;
            align-items: center;
            gap: 12px;
            color: #e6eef6;
            font-size: 14px;
            margin: 17px 0;
        }

        .rental-check {
            color: #ffc400;
            font-weight: bold;
            font-size: 19px;
        }

        .rental-login-left-footer {
            color: #b2cce0;
            font-size: 12px;
            margin-top: 35px;
        }

        .rental-login-right {
            padding: 42px 38px;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }

        .rental-login-right h2 {
            font-size: 29px;
            color: #041b34;
            margin: 0 0 9px;
        }

        .rental-login-description {
            color: #64748b;
            font-size: 14px;
            line-height: 1.6;
            margin-bottom: 20px;
        }

        .rental-login-right label {
            font-size: 13px;
            color: #102b46;
            font-weight: 700;
            margin: 15px 0 7px;
        }

        .rental-login-right input {
            width: 100%;
            border: 1px solid #d4deea;
            border-radius: 9px;
            padding: 14px;
            font-size: 14px;
            background: white;
        }

        .rental-login-right input:focus {
            outline: none;
            border-color: #00a99d;
            box-shadow: 0 0 0 3px rgba(0,169,157,.12);
        }

        .rental-login-submit {
            display: block;
            width: 100%;
            background: linear-gradient(
                90deg, #ffda61, #ffc400
            );
            color: #041b34;
            font-size: 15px;
            font-weight: 800;
            border: none;
            border-radius: 9px;
            padding: 15px;
            margin-top: 24px;
            cursor: pointer;
        }

        .rental-login-submit:hover {
            background: #edb800;
        }

        .rental-or {
            display: flex;
            align-items: center;
            gap: 12px;
            margin: 25px 0 17px;
            color: #8290a0;
            font-size: 12px;
        }

        .rental-or:before,
        .rental-or:after {
            content: "";
            flex: 1;
            height: 1px;
            background: #e2e8f0;
        }

        .rental-social-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
        }

        .rental-social-option {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 9px;
            min-height: 49px;
            padding: 11px 8px;
            border: 1px solid #dce4ed;
            border-radius: 10px;
            background: #f8fafc;
            color: #26384e;
            font-size: 13px;
            font-weight: 700;
            margin: 0;
            opacity: .72;
            cursor: not-allowed;
        }

        .rental-social-option:disabled {
            background: #f8fafc;
            color: #26384e;
        }

        .rental-social-icon {
            font-size: 21px;
            font-weight: 900;
            line-height: 1;
        }

        .rental-google {
            color: #4285f4;
        }

        .rental-facebook {
            color: #1877f2;
        }

        .rental-linkedin {
            color: #0a66c2;
            font-size: 18px;
        }

        .rental-apple {
            color: #111827;
            font-size: 23px;
        }

        .rental-social-status {
            color: #64748b;
            font-size: 11px;
            text-align: center;
            margin: 12px 0 0;
        }

        .rental-register-link {
            margin-top: 27px;
            text-align: center;
            color: #64748b;
            font-size: 13px;
        }

        .rental-register-link a {
            color: #007f91;
            font-weight: 800;
            text-decoration: none;
        }

        .rental-home-link {
            margin-top: 25px;
            text-align: center;
        }

        .rental-home-link a {
            color: #64748b;
            font-size: 13px;
            font-weight: 700;
            text-decoration: none;
        }

        @media (max-width: 760px) {
            .rental-login-layout {
                grid-template-columns: 1fr;
            }

            .rental-login-left {
                padding: 30px 24px;
            }

            .rental-login-left h1 {
                font-size: 27px;
                margin: 22px 0 12px;
            }

            .rental-login-right {
                padding: 32px 24px;
            }
        }

        @media (max-width: 380px) {
            .rental-social-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>

        <div class="rental-login-layout">

            <!-- LEFT SIDE: BUSINESS INTRODUCTION -->

            <section class="rental-login-left">

                <div>

                    <div class="rental-brand">
                        WE-SELL
                    </div>

                    <div class="rental-brand-sub">
                        Advertising & Connections
                    </div>

                    <h1>
                        Grow Your<br>
                        Rental Business.
                    </h1>

                    <p>
                        Manage your rental vehicles,
                        advertise your inventory, and
                        connect with potential customers
                        through one professional platform.
                    </p>

                    <div class="rental-feature">
                        <span class="rental-check">✓</span>
                        Manage your rental fleet
                    </div>

                    <div class="rental-feature">
                        <span class="rental-check">✓</span>
                        Advertise available vehicles
                    </div>

                    <div class="rental-feature">
                        <span class="rental-check">✓</span>
                        Connect with rental customers
                    </div>

                    <div class="rental-feature">
                        <span class="rental-check">✓</span>
                        Access your business dashboard
                    </div>

                </div>

                <div class="rental-login-left-footer">
                    WE-SELL Business Portal
                </div>

            </section>

            <!-- RIGHT SIDE: LOGIN -->

            <section class="rental-login-right">

                <h2>Welcome Back</h2>

                <p class="rental-login-description">
                    Sign in to your rental company account
                    to manage your business.
                </p>

                <form method="POST">

                    <input
                        type="hidden"
                        name="csrf"
                        value="{{ csrf }}"
                    >

                    <label for="rental-email">
                        Business Email Address
                    </label>

                    <input
                        id="rental-email"
                        type="email"
                        name="email"
                        placeholder="Enter your email address"
                        autocomplete="email"
                        required
                    >

                    <label for="rental-password">
                        Password
                    </label>

                    <input
                        id="rental-password"
                        type="password"
                        name="password"
                        placeholder="Enter your password"
                        autocomplete="current-password"
                        required
                    >

                    <button
                        type="submit"
                        class="rental-login-submit"
                    >
                        Sign In to Dashboard →
                    </button>

                </form>

                <div class="rental-or">
                    Or continue with
                </div>

                <!-- SOCIAL SIGN-IN OPTIONS -->
                <!-- Buttons remain disabled until
                     secure OAuth account linking
                     has been implemented. -->

                <div class="rental-social-grid">

                    <!-- GOOGLE / GMAIL -->

                    <button
                        type="button"
                        class="rental-social-option"
                        disabled
                        title="Google sign-in coming soon"
                    >
                        <span class="rental-social-icon rental-google">
                            G
                        </span>
                        Google / Gmail
                    </button>

                    <!-- FACEBOOK -->

                    <button
                        type="button"
                        class="rental-social-option"
                        disabled
                        title="Facebook sign-in coming soon"
                    >
                        <span class="rental-social-icon rental-facebook">
                            f
                        </span>
                        Facebook
                    </button>

                    <!-- LINKEDIN -->

                    <button
                        type="button"
                        class="rental-social-option"
                        disabled
                        title="LinkedIn sign-in coming soon"
                    >
                        <span class="rental-social-icon rental-linkedin">
                            in
                        </span>
                        LinkedIn
                    </button>

                    <!-- APPLE -->

                    <button
                        type="button"
                        class="rental-social-option"
                        disabled
                        title="Apple sign-in coming soon"
                    >
                        <span class="rental-social-icon rental-apple">
                            &#63743;
                        </span>
                        Apple
                    </button>

                </div>

                <p class="rental-social-status">
                    Social sign-in coming soon
                </p>

                <div class="rental-register-link">
                    New rental company?
                    <a href="{{ register_url }}">
                        Create a Business Account
                    </a>
                </div>

                <div class="rental-home-link">
                    <a href="/">
                        ← Return to WE-SELL Main Website
                    </a>
                </div>

            </section>

        </div>
        """,
        csrf=csrf_token(),
        register_url=url_for(
            "rental_portal.register"
        )
    )
