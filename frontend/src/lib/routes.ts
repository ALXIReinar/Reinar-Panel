export class AppRoutes {
    public static readonly BASE_URL = 'http://localhost:5173'

    public static Dashboard = () => `${this.BASE_URL}/dashboard`
    public static Login = () => `${this.Dashboard()}/login`
    public static Templates = () => `${this.Dashboard()}/templates`
    public static Protocols = () => `${this.Dashboard()}/protocols`
}
