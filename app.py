import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots 

# Load data with st.cache_data
@st.cache_data
def load_and_process_data():
    url = "https://docs.google.com/spreadsheets/d/1FKPhjul2X1qDdfcv3EneYOT08FN7lBsUaIGTS_j238g/export?format=csv"
    # Read the CSV file
    df = pd.read_csv(url, on_bad_lines="skip")

    # Add a column to classify as Subscription or Adspends
    df["Description"] = df["Description"].astype(str)

    df["Adspends / Subscription"] = df["Description"].apply(
        lambda x: "Subscription" if "subscription" in x.lower() else "Adspends"
    )

    if url == "https://docs.google.com/spreadsheets/d/1FKPhjul2X1qDdfcv3EneYOT08FN7lBsUaIGTS_j238g/export?format=csv":
        df['Gateway charges in USD'] = df['Fee']
        df = df.rename(columns={"Created date (UTC)": "Created date"})

    # Map status to new categories
    status_mapping = {
        "requires_payment_method": "Failed",
        "Failed": "Failed",
        "Pending": "Failed",
        "canceled": "Failed",
        "requires_confirmation": "Failed",
        "requires_action": "Failed",
        "Paid": "Paid",
        "Refunded": "Refunded"
    }
    df['Mapped Status'] = df["Status"]
    df["Status"] = df["Status"].map(status_mapping)

    

    # Convert numeric columns
    numeric_columns = [
        "Amount", "Amount Refunded", "Gateway charges in USD",
        "Overages in USD", "Converted Amount", "Converted Amount Refunded",
        "Fee", "Taxes On Fee", "Disputed Amount"
    ]
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # Convert date columns
    date_columns = [
        "Created date", "Refunded date (UTC)", "Dispute Date (UTC)",
        "Dispute Evidence Due (UTC)"
    ]
    for col in date_columns:
        if col in df.columns:
            if url == "https://docs.google.com/spreadsheets/d/1FKPhjul2X1qDdfcv3EneYOT08FN7lBsUaIGTS_j238g/export?format=csv":
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%d/%m/%Y")
            else:
                df[col] = pd.to_datetime(df[col], format="%d/%m/%Y", errors="coerce")
    # Return cleaned dataframe
    return df

# Load and process data
data = load_and_process_data()

# Display a sample of the cleaned data
if not data.empty:
    st.title("Payments Dashboard")
    st.write("Sample of Processed Data:")
    st.dataframe(data.head())
else:
    st.error("No data loaded. Please check the file.")


# Sidebar Navigation
st.sidebar.title("Payments Dashboard")
pages = ["Overview", "Customer Metrics", "Transactions","Refunds", "Disputes", "Adspends vs Subscriptions"]
selected_page = st.sidebar.selectbox("Select a Page", pages)

# Overview Page
if selected_page == "Overview":
    st.title("Overall Payment Metrics")

    # Metrics
    total_payment_value = data["Converted Amount"].sum()
    total_success = data[data["Status"] == "Paid"]["Converted Amount"].sum()
    total_failed = data[(data["Status"] != "Paid") & (data["Status"] != "Refunded")]["Converted Amount"].sum()
    total_gateway_charge = data["Gateway charges in USD"].sum()
    total_fee = data["Fee"].sum()
    total_refunded = data[data["Status"] == "Refunded"]["Converted Amount Refunded"].sum()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Payment Value", f"${total_payment_value:,.2f}")
        st.metric("Total Successful Payments", f"${total_success:,.2f}")
    with col2:
        st.metric("Total Failed Payments", f"${total_failed:,.2f}")
        st.metric("Total Gateway Charges", f"${total_gateway_charge:,.2f}")
    with col3:
        st.metric("Total Fee", f"${total_fee:,.2f}")
        st.metric("Total Refunded",f"${total_refunded:,.2f}")

    # Success vs Failed vs Refunded Pie Chart
    col1, col2 = st.columns(2)
    with col1:
        status_counts = data["Status"].value_counts()
        fig_pie = px.pie(
            names=status_counts.index,
            values=status_counts.values,
            title="Success vs Failed vs Refunded (Count)",
            labels={"index": "Status", "value": "Count"}
        )
        st.plotly_chart(fig_pie)
    with col2:
        status_amount = data.groupby("Status")["Converted Amount"].sum()
        fig_pie_amount = px.pie(
            names=status_amount.index,
            values=status_amount.values,
            title="Success vs Failed vs Refunded (Amount))",
            labels={"index": "Status", "value": "Converted Amount"}
        )
        st.plotly_chart(fig_pie_amount)

    # Revenue Over Time Grouped by Month
    st.write("Revenue Over Time (Grouped by Month)")
    data["Month"] = pd.to_datetime(data["Created date"], errors='coerce').dt.to_period("M").astype(str)

    monthly_revenue = data.groupby("Month")["Converted Amount"].sum().reset_index()
    fig_revenue = px.line(
        monthly_revenue,
        x="Month",
        y="Converted Amount",
        title="Monthly Revenue",
        labels={"Month": "Month", "Converted Amount": "Revenue"},
        markers=True,
        hover_data=["Converted Amount"]
    )

    # Add annotations for each data point
    for i, row in monthly_revenue.iterrows():
        fig_revenue.add_annotation(
            x=row["Month"],
            y=row["Converted Amount"],
            text=f"{row['Converted Amount']}",
            showarrow=False,
            font=dict(size=10, color="black"),
            bgcolor="white",
            bordercolor="black",
            borderwidth=1
        )

    st.plotly_chart(fig_revenue)
    
    
    
    # Correct Monthly Totals Calculation
    monthly_summary = data.groupby("Month").agg(
        Total_Payments=("Converted Amount", "sum"),
        Total_Refunded=("Converted Amount Refunded", lambda x: x[data.loc[x.index, "Status"] == "Refunded"].sum()),
        Total_Successful=("Converted Amount", lambda x: x[data.loc[x.index, "Status"] == "Paid"].sum()),
        Total_Failed=("Converted Amount", lambda x: x[data.loc[x.index, "Status"].isin(["Failed", "Other_Failed_Status"])].sum())
    ).reset_index()

    # Remove "Total Payments" from the visualization
    graph_data = monthly_summary.drop(columns=["Total_Payments"])

    # Melt data for visualization
    melted_graph_data = graph_data.melt(
        id_vars=["Month"], 
        var_name="Type", 
        value_name="Amount"
    )

    # Add tooltips by merging the original summary
    melted_graph_data = melted_graph_data.merge(
        monthly_summary,
        on="Month"
    )

    # Visualize Monthly Totals with a Stacked Bar Chart
    fig_monthly_totals = px.bar(
        melted_graph_data,
        x="Month",
        y="Amount",
        color="Type",
        title="Monthly Payment Breakdown (Refunded, Successful, Failed)",
        barmode="stack",
        labels={"Month": "Month", "Amount": "Amount ($)", "Type": "Category"},
    )

    # Use hovertemplate to control tooltip content
    fig_monthly_totals.update_traces(
        hovertemplate=(
            "Month: %{x}<br>"
            "Total Payment: %{customdata[3]:,.2f}<br>"
            "Total Refunded: %{customdata[0]:,.2f}<br>"
            "Total Successful: %{customdata[1]:,.2f}<br>"
            "Total Failed: %{customdata[2]:,.2f}<br>"
            "<extra></extra>"  # Removes the default trace info
        ),
        customdata=melted_graph_data[["Total_Refunded", "Total_Successful", "Total_Failed", "Total_Payments"]].values
    )

    # Display the chart
    st.plotly_chart(fig_monthly_totals)


    # Normalize data for 100% Stacked Bar Chart
    normalized_graph_data = melted_graph_data.copy()

    # Calculate percentages for each category within each month
    normalized_graph_data["Percentage"] = (
        normalized_graph_data["Amount"]
        / normalized_graph_data.groupby("Month")["Amount"].transform("sum")
        * 100
    )

    # Create a summary table for tooltips (percentages by type)
    tooltip_data = normalized_graph_data.pivot_table(
        index="Month",
        columns="Type",
        values="Percentage",
        aggfunc="sum"
    ).reset_index()

    # Rename columns for tooltip readability
    tooltip_data.columns = ["Month", "Refunded (%)", "Successful (%)", "Failed (%)"]

    # Merge tooltip data into normalized data
    normalized_graph_data = normalized_graph_data.merge(
        tooltip_data,
        on="Month"
    )

    # Create 100% Stacked Bar Chart
    fig_monthly_totals_stacked = px.bar(
        normalized_graph_data,
        x="Month",
        y="Percentage",
        color="Type",
        title="Monthly Payment Breakdown (100% Stacked)",
        barmode="relative",
        labels={"Month": "Month", "Percentage": "Percentage (%)", "Type": "Category"},
    )

    # Update hovertemplate to include Month and percentages for all categories
    fig_monthly_totals_stacked.update_traces(
        hovertemplate=(
            "Month: %{x}<br>"
            "Refunded: %{customdata[0]:.2f}%<br>"
            "Successful: %{customdata[1]:.2f}%<br>"
            "Failed: %{customdata[2]:.2f}%<br>"
            "<extra></extra>"
        ),
        customdata=normalized_graph_data[["Refunded (%)", "Successful (%)", "Failed (%)"]].values
    )

    # Show the chart
    st.plotly_chart(fig_monthly_totals_stacked)


    # Adspends and Subscription: Month X Total Payment, Success, Failed, Refund
    for category in ["Adspends", "Subscription"]:
        st.write(f"{category} Monthly Breakdown")
        category_data = data[data["Adspends / Subscription"] == category]
        category_summary = category_data.groupby("Month").agg({
            "Converted Amount": "sum",
            "Status": lambda x: (x == "Paid").sum(),
            "Converted Amount Refunded": "sum"
        }).rename(columns={"Converted Amount": "Total Payment", "Status": "Successful Payments"})
        category_summary["Failed Payments"] = category_data[(category_data["Status"] != "Paid") & (category_data["Status"] != "Refunded")].groupby("Month")["Converted Amount"].sum()
        category_summary = category_summary.reset_index()

        fig_category = px.bar(
            category_summary.melt(id_vars=["Month"], var_name="Type", value_name="Amount"),
            x="Month",
            y="Amount",
            color="Type",
            title=f"{category} Monthly Payment Breakdown",
            barmode="group"
        )
        st.plotly_chart(fig_category)

    # Bar Graph: Descending Order of Card Address Country
    st.write("Payments by Card Address Country")
    country_summary = data.groupby("Card Address Country")["Converted Amount"].sum().reset_index()
    country_summary = country_summary.sort_values(by="Converted Amount", ascending=False)
    fig_country = px.bar(
        country_summary,
        x="Card Address Country",
        y="Converted Amount",
        title="Payments by Country",
        labels={"Card Address Country": "Country", "Converted Amount": "Total Payment"}
    )
    st.plotly_chart(fig_country)

    # Failed Payments Reason Analysis
    st.write("Failed Payments Reason Analysis")
    failed_reasons = data[(data["Status"] != "Paid") & (data["Status"] != "Refunded")]["Decline Reason"].value_counts().reset_index()
    failed_reasons.columns = ["Decline Reason", "Count"]
    fig_failed_reasons = px.bar(
        failed_reasons,
        x="Decline Reason",
        y="Count",
        title="Overall Failed Payments Reason Analysis",
        labels={"Decline Reason": "Reason", "Count": "Occurrences"}
    )
    st.plotly_chart(fig_failed_reasons)

    for category in ["Adspends", "Subscription"]:
        st.write(f"{category} Failed Payments Reason Analysis")
        category_failed = data[(data["Adspends / Subscription"] == category) & (data["Status"] != "Paid") & (data["Status"] != "Refunded")]
        category_reasons = category_failed["Decline Reason"].value_counts().reset_index()
        category_reasons.columns = ["Decline Reason", "Count"]
        fig_category_reasons = px.bar(
            category_reasons,
            x="Decline Reason",
            y="Count",
            title=f"{category} Failed Payments Reason Analysis",
            labels={"Decline Reason": "Reason", "Count": "Occurrences"}
        )
        st.plotly_chart(fig_category_reasons)


# Other Pages
elif selected_page == "Customer Metrics":
    st.title("Customer-Level Metrics")
    email = st.text_input("Enter Customer Email:")
    if email:
        customer_data = data[data['Customer Email'] == email]
        if not customer_data.empty:
            st.write(f"Metrics for {email}:")
            st.metric("Total Payments", customer_data['Amount'].sum())
            st.metric("Total Refunds", customer_data['Amount Refunded'].sum())
            st.metric("Total Transactions", customer_data.shape[0])
            st.dataframe(customer_data)
        else:
            st.warning("No data found for this email.")


elif selected_page == "Transactions":
    st.title("Transaction Details")
    st.write("Explore all transactions with filters, sorting, and search.")

    # Filters
    status_filter = st.multiselect("Select Status", data["Status"].unique())
    captured_filter = st.selectbox("Captured?", ["All", "Yes", "No"])
    adspends_filter = st.selectbox("Adspends / Subscription", ["All"] + data["Adspends / Subscription"].unique().tolist())
    date_range = st.date_input("Select Date Range", [])

    filtered_data = data.copy()

    # Apply Filters
    if status_filter:
        filtered_data = filtered_data[filtered_data["Status"].isin(status_filter)]
    if captured_filter == "Yes":
        filtered_data = filtered_data[filtered_data["Captured"] == True]
    elif captured_filter == "No":
        filtered_data = filtered_data[filtered_data["Captured"] == False]
    if adspends_filter != "All":
        filtered_data = filtered_data[filtered_data["Adspends / Subscription"] == adspends_filter]
    if date_range:
        filtered_data = filtered_data[
            (filtered_data["Created date"] >= pd.Timestamp(date_range[0])) &
            (filtered_data["Created date"] <= pd.Timestamp(date_range[1]))
        ]

    # Search Functionality
    search_term = st.text_input("Search by PaymentIntent ID or Customer ID")
    if search_term:
        filtered_data = filtered_data[
            filtered_data["PaymentIntent ID"].str.contains(search_term, na=False) |
            filtered_data["Customer ID"].str.contains(search_term, na=False)
        ]

    # Display Table
    st.dataframe(filtered_data)

    # Export to CSV
    st.download_button(
        label="Download Filtered Data as CSV",
        data=filtered_data.to_csv(index=False),
        file_name="filtered_transactions.csv",
        mime="text/csv"
    )


elif selected_page == "Refunds":
    st.title("Refunds Dashboard")
    st.write("Overview and analysis of refunds.")

    # Metrics
    total_refunded_amount = data["Amount Refunded"].sum()
    total_refunds = data[data["Amount Refunded"] > 0].shape[0]

    st.metric("Total Refunded Amount", f"${total_refunded_amount:,.2f}")
    st.metric("Total Refunds", total_refunds)

    # Refund Trends Over Time
    st.write("Refund Trends Over Time:")
    refund_trends = data[data["Amount Refunded"] > 0].groupby("Created date").agg({
        "Amount Refunded": "sum"
    }).reset_index()
    
    # Use Plotly for the line chart
    fig_trends = px.line(
        refund_trends,
        x="Created date",
        y="Amount Refunded",
        title="Refund Trends Over Time",
        labels={"Created date": "Date", "Amount Refunded": "Refunded Amount"}
    )
    st.plotly_chart(fig_trends)

    # Breakdown by Currency
    st.write("Refund Breakdown by Currency:")
    refund_by_currency = data[data["Amount Refunded"] > 0].groupby("Currency").agg({
        "Amount Refunded": "sum"
    }).reset_index()
    
    # Use Plotly for the bar chart
    fig_currency = px.bar(
        refund_by_currency,
        x="Currency",
        y="Amount Refunded",
        title="Refunds by Currency",
        labels={"Currency": "Currency", "Amount Refunded": "Refunded Amount"}
    )
    st.plotly_chart(fig_currency)

    # Refund Filters
    st.write("Filter Refund Data:")
    date_range = st.date_input("Select Date Range", [])
    refund_status = st.selectbox("Select Refund Status", ["All", "Successful", "Failed"])
    filtered_refunds = data[data["Amount Refunded"] > 0].copy()

    # Apply Filters
    if date_range:
        filtered_refunds = filtered_refunds[
            (filtered_refunds["Created date"] >= pd.Timestamp(date_range[0])) &
            (filtered_refunds["Created date"] <= pd.Timestamp(date_range[1]))
        ]
    if refund_status != "All":
        filtered_refunds = filtered_refunds[filtered_refunds["Status"].str.lower() == refund_status.lower()]

    # Refund Details Table
    st.write("Refund Details:")
    st.dataframe(filtered_refunds)

    # Export Filtered Refunds to CSV
    st.download_button(
        label="Download Filtered Refund Data as CSV",
        data=filtered_refunds.to_csv(index=False),
        file_name="filtered_refunds.csv",
        mime="text/csv"
    )

elif selected_page == "Disputes":
    st.title("Disputes Dashboard")
    st.write("Overview and analysis of disputes.")

    # Metrics
    total_disputed_amount = data["Disputed Amount"].sum()
    total_disputes = data["Dispute Date (UTC)"].count()

    st.metric("Total Disputed Amount", f"${total_disputed_amount:,.2f}")
    st.metric("Total Disputes", total_disputes)

    # Breakdown by Dispute Reason and Status
    st.write("Dispute Breakdown:")
    dispute_reason_counts = data["Dispute Reason"].value_counts()
    st.bar_chart(dispute_reason_counts)

    dispute_status_counts = data["Dispute Status"].value_counts()
    st.bar_chart(dispute_status_counts)

    # Dispute Trends Over Time
    st.write("Dispute Trends Over Time:")
    dispute_trends = data.groupby("Dispute Date (UTC)")["Disputed Amount"].sum().reset_index()
    st.line_chart(dispute_trends, x="Dispute Date (UTC)", y="Disputed Amount")

    # List of Disputes with Filters
    dispute_due_filter = st.date_input("Filter by Evidence Due Date")
    filtered_disputes = data.copy()
    if dispute_due_filter:
        filtered_disputes = filtered_disputes[
            pd.to_datetime(filtered_disputes["Dispute Evidence Due (UTC)"], errors='coerce') <= pd.to_datetime(dispute_due_filter)
        ]

    st.dataframe(filtered_disputes)

elif selected_page == "Adspends vs Subscriptions":
    st.title("Adspends vs Subscriptions")
    st.write("Breakdown and analysis of revenue, refunds, and charges by type.")

    # Aggregate Data by Category
    category_summary = data.groupby("Adspends / Subscription").agg({
        "Amount": "sum",
        "Amount Refunded": "sum",
        "Gateway charges in USD": "sum"
    }).reset_index()

    # Display Summary Table
    st.write("Summary by Category:")
    st.dataframe(category_summary)

    # Revenue Trends by Category
    st.write("Revenue Trends by Category:")
    revenue_trends = data.groupby(["Adspends / Subscription", "Created date"]).agg({
        "Amount": "sum"
    }).reset_index()

    # Create a Plotly Line Chart for Each Category
    for category in revenue_trends["Adspends / Subscription"].unique():
        category_data = revenue_trends[revenue_trends["Adspends / Subscription"] == category]
        fig = px.line(
            category_data,
            x="Created date",
            y="Amount",
            title=f"{category} Revenue Trend Over Time",
            labels={"Created date": "Date", "Amount": "Revenue"},
        )
        st.plotly_chart(fig)


    # Revenue Trends with Dual Axes
    st.write("Revenue Trends by Category (Dual Axes):")
    revenue_trends = data.groupby(["Created date", "Adspends / Subscription"]).agg({
        "Amount": "sum"
    }).reset_index()

    adspends_data = revenue_trends[revenue_trends["Adspends / Subscription"] == "Adspends"]
    subscriptions_data = revenue_trends[revenue_trends["Adspends / Subscription"] == "Subscription"]

    fig_dual_axes = make_subplots(specs=[[{"secondary_y": True}]])

    # Add Adspends to the left y-axis
    fig_dual_axes.add_trace(
        go.Scatter(
            x=adspends_data["Created date"],
            y=adspends_data["Amount"],
            name="Adspends",
            mode="lines",
            line=dict(color="blue")
        ),
        secondary_y=False,
    )

    # Add Subscriptions to the right y-axis
    fig_dual_axes.add_trace(
        go.Scatter(
            x=subscriptions_data["Created date"],
            y=subscriptions_data["Amount"],
            name="Subscriptions",
            mode="lines",
            line=dict(color="orange")
        ),
        secondary_y=True,
    )

    # Update axis titles
    fig_dual_axes.update_layout(
        title="Adspends and Subscriptions Revenue Trends (Dual Axes)",
        xaxis_title="Date",
        yaxis_title="Adspends Revenue",
        yaxis2_title="Subscriptions Revenue",
    )

    st.plotly_chart(fig_dual_axes)

    # Refunds by Category
    st.write("Refunds by Category:")
    fig_refunds = px.bar(
        category_summary,
        x="Adspends / Subscription",
        y="Amount Refunded",
        title="Refunds by Category",
        labels={"Adspends / Subscription": "Category", "Amount Refunded": "Refunded Amount"},
    )
    st.plotly_chart(fig_refunds)

    # Gateway Charges by Category
    st.write("Gateway Charges by Category:")
    fig_charges = px.bar(
        category_summary,
        x="Adspends / Subscription",
        y="Gateway charges in USD",
        title="Gateway Charges by Category",
        labels={"Adspends / Subscription": "Category", "Gateway charges in USD": "Gateway Charges"},
    )
    st.plotly_chart(fig_charges)

    st.write("Monthly Amount by Category (Dual Axes):")

    # Prepare Data
    data["Year-Month"] = data["Created date"].dt.to_period("M").astype(str)
    gateway_monthly = data.groupby(["Year-Month", "Adspends / Subscription"]).agg({
        "Converted Amount": "sum"
    }).reset_index()
    gateway_monthly = gateway_monthly.rename(columns={"Converted Amount": "Amount in USD"})
    st.dataframe(gateway_monthly)

    # Separate Data for Adspends and Subscriptions
    adspends_data = gateway_monthly[gateway_monthly["Adspends / Subscription"] == "Adspends"]
    subscriptions_data = gateway_monthly[gateway_monthly["Adspends / Subscription"] == "Subscription"]

    # Create Subplots with Secondary Y-axis
    fig_dual_axes = make_subplots(specs=[[{"secondary_y": True}]])

    # Add Adspends to the left Y-axis
    fig_dual_axes.add_trace(
        go.Bar(
            x=adspends_data["Year-Month"],
            y=adspends_data["Amount in USD"],
            name="Adspends",
            marker=dict(color="blue")
        ),
        secondary_y=False,
    )

    # Add Subscriptions to the right Y-axis
    fig_dual_axes.add_trace(
        go.Bar(
            x=subscriptions_data["Year-Month"],
            y=subscriptions_data["Amount in USD"],
            name="Subscriptions",
            marker=dict(color="orange")
        ),
        secondary_y=True,
    )

    # Update Axes Titles
    fig_dual_axes.update_layout(
        title="Monthly Amount by Category (Dual Axes)",
        xaxis_title="Month",
        yaxis_title="Adspends Amount",
        yaxis2_title="Subscriptions Amount",
        barmode="group",
        legend_title="Category",
    )

    # Show Plot
    st.plotly_chart(fig_dual_axes)