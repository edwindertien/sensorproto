$fn=50;
base();

top();
module top(){
difference(){
translate([0,0,30.5])cube([20,44,19.5]);
    translate([0,22,30])rotate([0,90,0])cylinder(d=33.5,h=20);
    
        translate([3,3,30])cylinder(d=3.2,h=33);
    translate([20-3,3,30])cylinder(d=3.2,h=33);
    
    translate([3,44-3,30])cylinder(d=3.2,h=33);
    translate([20-3,44-3,30])cylinder(d=3.2,h=33);
    
            translate([3,3,50-3])cylinder(d=5,h=33);
    translate([20-3,3,50-3])cylinder(d=5,h=33);
    
    translate([3,44-3,50-3])cylinder(d=5,h=33);
    translate([20-3,44-3,50-3])cylinder(d=5,h=33);
}    
}

module base(){
difference(){
    union(){
        cube([20,44,29.5]);
        
    }
    translate([0,22,30])rotate([0,90,0])cylinder(d=33.5,h=20);
    translate([10,0,20])rotate([-90,0,0])cylinder(d=5,h=50);
    
    translate([10,17,0])cylinder(d=5,h=20);
    translate([10,27,0])cylinder(d=5,h=20);
        translate([10,17,8])cylinder(d=8,h=20);
    translate([10,27,8])cylinder(d=8,h=20);
    
    translate([3,3,0])cylinder(d=2.7,h=33);
    translate([20-3,3,0])cylinder(d=2.7,h=33);
    
    translate([3,44-3,0])cylinder(d=2.7,h=33);
    translate([20-3,44-3,0])cylinder(d=2.7,h=33);
}}